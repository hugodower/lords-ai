from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from typing import Optional

from fastapi import FastAPI, File, Query, Request, UploadFile
from fastapi.responses import JSONResponse

from app.config import settings
from app.agents.sdr import sdr_agent
from app.agents.support import support_agent
from app.guards.debounce import debounce_message
from app.integrations import supabase_client as sb
from app.knowledge.rag import index_document, search_knowledge, ping_chroma
from app.memory.redis_store import is_paused, ping_redis, set_paused
from app.services.followup_worker import start_worker as start_followup_worker, stop_worker as stop_followup_worker
from app.models.schemas import (
    AgentsStatusResponse,
    AgentStatusItem,
    HealthResponse,
    KnowledgeSearchResult,
    KnowledgeUploadResponse,
    LogEntry,
    LogsResponse,
    MetricsResponse,
    ProcessMessageRequest,
    ProcessMessageResponse,
)
from app.utils.logger import get_logger

log = get_logger("main")

AGENTS = {
    "sdr": sdr_agent,
    "support": support_agent,
}

# Maps Chatwoot inbox channel_type to user-facing channel name
CHANNEL_MAP = {
    "Channel::Api": "WhatsApp",
    "Channel::Whatsapp": "WhatsApp",
    "Channel::WebWidget": "Site",
    "Channel::FacebookPage": "Messenger",
    "Channel::Instagram": "Instagram",
    "Channel::Email": "Email",
    "Channel::Telegram": "Telegram",
    "Channel::Sms": "SMS",
    "Channel::Line": "Line",
}


_followup_task: Optional[asyncio.Task] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _followup_task
    log.info("LORDS-AI starting for org %s", settings.org_id)
    logging.getLogger().setLevel(settings.log_level)

    # Start follow-up worker background task
    _followup_task = asyncio.create_task(start_followup_worker())
    log.info("[FOLLOWUP:WORKER] Background task created")

    yield

    # Graceful shutdown of follow-up worker
    stop_followup_worker()
    if _followup_task and not _followup_task.done():
        _followup_task.cancel()
        try:
            await _followup_task
        except asyncio.CancelledError:
            pass
    log.info("LORDS-AI shutting down")


app = FastAPI(
    title="LORDS AI Agents",
    version="0.1.0",
    lifespan=lifespan,
)


# ── Health ───────────────────────────────────────────────────────────


@app.get("/health", response_model=HealthResponse)
async def health():
    agents_active = []
    try:
        active = await sb.get_active_agents(settings.org_id)
        agents_active = [a["agent_type"] for a in active]
    except Exception:
        pass

    redis_ok = await ping_redis()
    chroma_ok = ping_chroma()

    return HealthResponse(
        status="ok",
        org_id=settings.org_id,
        agents_active=agents_active,
        redis="connected" if redis_ok else "disconnected",
        chroma="connected" if chroma_ok else "disconnected",
    )


# ── Process message ──────────────────────────────────────────────────


@app.post("/api/v1/process-message", response_model=ProcessMessageResponse)
async def process_message(req: ProcessMessageRequest):
    org_id = req.org_id or settings.org_id

    # Determine which agent to use based on active configs
    active = await sb.get_active_agents(org_id)
    active_types = {a["agent_type"] for a in active}

    # Priority: SDR first, then support
    agent = None
    for agent_type in ["sdr", "support"]:
        if agent_type in active_types and agent_type in AGENTS:
            agent = AGENTS[agent_type]
            break

    if not agent:
        return ProcessMessageResponse(
            action="ignored",
            error="No active agent for this org",
        )

    return await agent.process(
        org_id=org_id,
        conversation_id=req.conversation_id,
        contact_phone=req.contact_phone,
        contact_name=req.contact_name,
        message=req.message,
        channel=req.channel,
    )


# ── Chatwoot webhook ─────────────────────────────────────────────────


@app.post("/api/v1/webhook/chatwoot")
async def chatwoot_webhook(request: Request):
    try:
        payload = await request.json()
    except Exception as exc:
        log.error("[WEBHOOK] Failed to parse JSON body: %s", exc)
        return JSONResponse({"status": "error", "reason": "invalid_json", "detail": str(exc)})

    # Filters
    event = payload.get("event")
    if event != "message_created":
        return JSONResponse({"status": "ignored", "reason": "event_not_message_created"})

    message_type = payload.get("message_type")
    if message_type != "incoming":
        return JSONResponse({"status": "ignored", "reason": "not_incoming"})

    if payload.get("private") is True:
        return JSONResponse({"status": "ignored", "reason": "private_note"})

    # Guard: skip if conversation has a human agent assigned
    conversation = payload.get("conversation") or {}
    assignee = conversation.get("assignee")
    if assignee and assignee.get("id"):
        agent_name = assignee.get("name") or assignee.get("email") or assignee.get("id")
        conv_id = conversation.get("id", "?")
        log.info(
            "[WEBHOOK] Conversa %s tem agente humano atribuído (%s), ignorando",
            conv_id, agent_name,
        )
        return JSONResponse({"status": "ignored", "reason": "human_assigned"})

    # Guard: skip if message is from the bot/AI itself (avoid loop)
    sender = payload.get("sender") or {}
    sender_type = sender.get("type")
    sender_id = sender.get("id")
    bot_id = settings.chatwoot_bot_agent_id
    if sender_type == "agent_bot" or (bot_id and sender_id == bot_id):
        log.info(
            "[WEBHOOK] Mensagem do próprio bot/agente (sender.id=%s, type=%s), ignorando",
            sender_id, sender_type,
        )
        return JSONResponse({"status": "ignored", "reason": "self_message"})

    content = (payload.get("content") or "").strip()
    if not content:
        return JSONResponse({"status": "ignored", "reason": "empty_content"})

    try:
        # Extract data
        log.info("[WEBHOOK] Extraindo dados do payload...")
        inbox = payload.get("inbox") or {}
        account = payload.get("account") or {}

        account_id = account.get("id") or payload.get("account_id")
        conversation_id = str(conversation.get("id", ""))

        # Resolve channel from inbox type
        channel_type = inbox.get("channel_type", "")
        channel = CHANNEL_MAP.get(channel_type, "WhatsApp")

        contact_phone = (
            sender.get("phone_number")
            or (conversation.get("meta", {}).get("sender", {}).get("phone_number"))
            or ""
        )
        contact_name = (
            sender.get("name")
            or (conversation.get("meta", {}).get("sender", {}).get("name"))
            or ""
        )
        chatwoot_contact_id = str(sender.get("id", ""))

        log.info(
            "[WEBHOOK] Dados extraídos: account_id=%s conv=%s phone=%s name=%s channel=%s (inbox_type=%s)",
            account_id, conversation_id, contact_phone, contact_name, channel, channel_type,
        )

        # Resolve org_id from chatwoot_account_id
        log.info("[WEBHOOK] Buscando org para account_id=%s...", account_id)
        org_id = None
        if account_id:
            org_id = await sb.get_org_by_chatwoot_account(int(account_id))

        if not org_id:
            org_id = settings.org_id
            log.warning(
                "[WEBHOOK] Org não encontrada para account_id=%s, usando default %s",
                account_id, org_id,
            )

        log.info(
            "[WEBHOOK] org=%s conv=%s phone=%s name=%s msg=%s",
            org_id, conversation_id, contact_phone, contact_name, content[:50],
        )

        # Determine agent and process
        log.info("[WEBHOOK] Buscando agentes ativos para org=%s...", org_id)
        active = await sb.get_active_agents(org_id)
        active_types = {a["agent_type"] for a in active}
        log.info("[WEBHOOK] Agentes ativos: %s", active_types)

        agent = None
        for agent_type in ["sdr", "support"]:
            if agent_type in active_types and agent_type in AGENTS:
                agent = AGENTS[agent_type]
                break

        if not agent:
            log.warning("[WEBHOOK] Nenhum agente ativo para org=%s", org_id)
            return JSONResponse({"status": "ignored", "reason": "no_active_agent"})

        # Debounce: buffer messages for 4s, then process all at once
        log.info("[WEBHOOK] Debouncing message for conv=%s agent=%s", conversation_id, agent_type)

        async def _process_debounced(combined_message: str) -> None:
            result = await agent.process(
                org_id=org_id,
                conversation_id=conversation_id,
                contact_phone=contact_phone,
                contact_name=contact_name,
                message=combined_message,
                chatwoot_contact_id=chatwoot_contact_id,
                channel=channel,
            )
            log.info(
                "[WEBHOOK] Debounced result: conv=%s action=%s agent=%s",
                conversation_id, result.action, result.agent_type,
            )

        await debounce_message(conversation_id, content, _process_debounced)

        return JSONResponse({
            "status": "debounced",
            "conversation_id": conversation_id,
        })

    except Exception as exc:
        import traceback
        tb = traceback.format_exc()
        log.error("[WEBHOOK] ERRO no processamento: %s\n%s", exc, tb)
        return JSONResponse(
            {"status": "error", "reason": str(exc), "traceback": tb},
            status_code=500,
        )


# ── Knowledge base ──────────────────────────────────────────────────


@app.post("/api/v1/knowledge/upload", response_model=KnowledgeUploadResponse)
async def upload_knowledge(file: UploadFile = File(...)):
    content = await file.read()
    text = content.decode("utf-8", errors="ignore")
    chunks = await index_document(settings.org_id, file.filename or "upload", text)
    return KnowledgeUploadResponse(
        status="indexed",
        chunks=chunks,
        document_name=file.filename or "upload",
    )


@app.get("/api/v1/knowledge/search")
async def search_kb(q: str = Query(...), limit: int = Query(5)):
    results = await search_knowledge(settings.org_id, q, limit=limit)
    return {
        "results": [
            KnowledgeSearchResult(
                text=r["text"],
                score=r.get("score", 0),
                metadata=r.get("metadata", {}),
            )
            for r in results
        ]
    }


# ── Agent controls ───────────────────────────────────────────────────


@app.get("/api/v1/agents/status", response_model=AgentsStatusResponse)
async def agents_status():
    active = await sb.get_active_agents(settings.org_id)
    items = []
    for a in active:
        # Get today's stats
        today = datetime.utcnow().strftime("%Y-%m-%dT00:00:00")
        logs_data, _ = await sb.get_conversation_logs(
            settings.org_id, page=1, limit=1000, date_from=today
        )
        agent_logs = [l for l in logs_data if l.get("agent_type") == a["agent_type"]]
        messages = sum(1 for l in agent_logs if l.get("message_role") == "assistant")
        handoffs = sum(1 for l in agent_logs if l.get("action_taken") == "handoff")

        items.append(
            AgentStatusItem(
                type=a["agent_type"],
                name=a.get("agent_name", "Ana"),
                is_active=a.get("is_active", True),
                messages_today=messages,
                handoffs_today=handoffs,
            )
        )
    return AgentsStatusResponse(agents=items)


@app.post("/api/v1/agents/pause")
async def pause_agents():
    await set_paused(True)
    log.warning("Agents PAUSED via API")
    return {"status": "paused"}


@app.post("/api/v1/agents/resume")
async def resume_agents():
    await set_paused(False)
    log.info("Agents RESUMED via API")
    return {"status": "active"}


# ── Logs ─────────────────────────────────────────────────────────────


@app.get("/api/v1/logs", response_model=LogsResponse)
async def get_logs(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    date_from: Optional[str] = Query(None),
):
    logs, total = await sb.get_conversation_logs(
        settings.org_id, page=page, limit=limit, date_from=date_from
    )
    return LogsResponse(
        logs=[LogEntry(**l) for l in logs],
        total=total,
        page=page,
    )


# ── Metrics ──────────────────────────────────────────────────────────


@app.get("/api/v1/metrics", response_model=MetricsResponse)
async def get_metrics(period: str = Query("today")):
    now = datetime.utcnow()
    if period == "week":
        date_from = (now - timedelta(days=7)).isoformat()
    elif period == "month":
        date_from = (now - timedelta(days=30)).isoformat()
    else:  # today
        date_from = now.strftime("%Y-%m-%dT00:00:00")

    m = await sb.get_metrics(settings.org_id, date_from)
    return MetricsResponse(**m)


# ── Debug: Google Calendar ──────────────────────────────────────────


# ── Follow-up management ─────────────────────────────────────────────


@app.get("/api/v1/followups/pending")
async def get_followup_pending():
    """List pending follow-ups for this org."""
    from datetime import datetime as _dt, timezone as _tz, timedelta as _td
    BRT = _tz(_td(hours=-3))
    now = _dt.now(BRT).isoformat()
    # Get all pending (not just due ones)
    try:
        _sb = sb.get_supabase()
        resp = (
            _sb.table("followup_queue")
            .select("*")
            .eq("organization_id", settings.org_id)
            .eq("status", "pending")
            .order("scheduled_at")
            .limit(100)
            .execute()
        )
        return {"pending": resp.data or [], "count": len(resp.data or [])}
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


@app.get("/api/v1/followups/stats")
async def get_followup_stats():
    """Get follow-up statistics for this org."""
    try:
        _sb = sb.get_supabase()
        resp = (
            _sb.table("followup_queue")
            .select("status", count="exact")
            .eq("organization_id", settings.org_id)
            .execute()
        )
        rows = resp.data or []
        stats = {"pending": 0, "sent": 0, "cancelled": 0, "failed": 0}
        for row in rows:
            s = row.get("status", "")
            if s in stats:
                stats[s] += 1
        stats["total"] = sum(stats.values())
        return stats
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


@app.post("/api/v1/followups/cancel/{conversation_id}")
async def cancel_followups(conversation_id: int):
    """Manually cancel all pending follow-ups for a conversation."""
    from app.services.followup_scheduler import cancel_pending_followups
    count = await cancel_pending_followups(conversation_id, reason="manual cancel via API")
    return {"cancelled": count, "conversation_id": conversation_id}


# ── Debug: Google Calendar ──────────────────────────────────────────


@app.get("/debug/calendar")
async def debug_calendar():
    """Diagnostic endpoint to verify Google Calendar config in production."""
    from app.integrations.google_calendar import GoogleCalendarClient
    import httpx

    result: dict = {
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "org_id": settings.org_id,
        "env": {
            "google_client_id": settings.google_client_id[:10] + "..." if settings.google_client_id else "EMPTY",
            "google_client_secret": settings.google_client_secret[:5] + "..." if settings.google_client_secret else "EMPTY",
            "supabase_url": settings.supabase_url,
        },
        "scheduling_config": None,
        "token_info": None,
        "refresh_test": None,
    }

    # 1) Fetch scheduling_config
    try:
        config = await sb.get_scheduling_config(settings.org_id)
        if config:
            token = config.get("google_oauth_token")
            token_summary = None
            if token and isinstance(token, dict):
                expiry = token.get("expiry_date", 0)
                now_ms = datetime.utcnow().timestamp() * 1000
                remaining_min = (expiry - now_ms) / 60_000
                token_summary = {
                    "has_access_token": bool(token.get("access_token")),
                    "has_refresh_token": bool(token.get("refresh_token")),
                    "expiry_date": expiry,
                    "remaining_minutes": round(remaining_min, 1),
                    "expired": remaining_min <= 0,
                    "token_keys": list(token.keys()),
                }
            elif token:
                token_summary = {"error": f"token is {type(token).__name__}, expected dict"}

            result["scheduling_config"] = {
                "scheduling_type": config.get("scheduling_type"),
                "google_calendar_id": config.get("google_calendar_id"),
                "google_calendar_email": config.get("google_calendar_email"),
                "slot_duration_minutes": config.get("slot_duration_minutes"),
                "has_oauth_token": token is not None,
            }
            result["token_info"] = token_summary

            # 2) Try token refresh
            if token and isinstance(token, dict) and token.get("refresh_token"):
                try:
                    client_id = settings.google_client_id
                    client_secret = settings.google_client_secret
                    if not client_id or not client_secret:
                        result["refresh_test"] = {"status": "skipped", "reason": "missing client_id or client_secret in env"}
                    else:
                        async with httpx.AsyncClient(timeout=15) as client:
                            resp = await client.post(
                                "https://oauth2.googleapis.com/token",
                                data={
                                    "client_id": client_id,
                                    "client_secret": client_secret,
                                    "refresh_token": token["refresh_token"],
                                    "grant_type": "refresh_token",
                                },
                            )
                        if resp.status_code == 200:
                            new_tokens = resp.json()
                            new_expiry = int(datetime.utcnow().timestamp() * 1000) + (new_tokens.get("expires_in", 3600) * 1000)

                            # Save refreshed token
                            token["access_token"] = new_tokens["access_token"]
                            token["expiry_date"] = new_expiry
                            if "refresh_token" in new_tokens:
                                token["refresh_token"] = new_tokens["refresh_token"]
                            await sb.update_scheduling_token(settings.org_id, token)

                            result["refresh_test"] = {
                                "status": "success",
                                "new_expires_in_seconds": new_tokens.get("expires_in"),
                                "new_expiry_date": new_expiry,
                                "token_saved_to_supabase": True,
                            }
                        else:
                            result["refresh_test"] = {
                                "status": "failed",
                                "http_status": resp.status_code,
                                "error": resp.text[:500],
                            }
                except Exception as exc:
                    result["refresh_test"] = {"status": "error", "exception": str(exc)}
            else:
                result["refresh_test"] = {"status": "skipped", "reason": "no refresh_token in config"}
        else:
            result["scheduling_config"] = {"error": "no scheduling_config row for this org_id"}
    except Exception as exc:
        result["scheduling_config"] = {"error": str(exc)}

    return JSONResponse(result)
