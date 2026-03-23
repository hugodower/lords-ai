from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from typing import Optional

from fastapi import FastAPI, File, Query, UploadFile
from fastapi.responses import JSONResponse

from app.config import settings
from app.agents.sdr import sdr_agent
from app.agents.support import support_agent
from app.integrations import supabase_client as sb
from app.knowledge.rag import index_document, search_knowledge, ping_chroma
from app.memory.redis_store import is_paused, ping_redis, set_paused
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


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("LORDS-AI starting for org %s", settings.org_id)
    logging.getLogger().setLevel(settings.log_level)
    yield
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
