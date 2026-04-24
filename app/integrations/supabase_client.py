from __future__ import annotations

from typing import Any, Optional

from supabase import create_client, Client

from app.config import settings
from app.utils.logger import get_logger

log = get_logger("supabase")

_client: Optional[Client] = None


def get_supabase() -> Client:
    global _client
    if _client is None:
        _client = create_client(settings.supabase_url, settings.supabase_service_key)
        log.info("Supabase client initialized")
    return _client


# ── Agent config ─────────────────────────────────────────────────────


async def get_agent_config(org_id: str, agent_type: str) -> Optional[dict]:
    sb = get_supabase()
    try:
        resp = (
            sb.table("agent_configs")
            .select("*")
            .eq("organization_id", org_id)
            .eq("agent_type", agent_type)
            .eq("is_active", True)
            .maybe_single()
            .execute()
        )
        if resp and resp.data:
            log.info(
                "[CONFIG] Loaded agent_config for org=%s type=%s — name=%s, personality=%s chars, sandbox=%s",
                org_id, agent_type,
                resp.data.get("agent_name", "?"),
                len(resp.data.get("personality") or ""),
                resp.data.get("sandbox_mode", False),
            )
        else:
            log.warning("[CONFIG] No active agent_config found for org=%s type=%s", org_id, agent_type)
        return resp.data if resp else None
    except Exception as exc:
        log.error("[CONFIG] FAILED to load agent_config for org=%s type=%s: %s", org_id, agent_type, exc)
        return None


async def get_active_agents(org_id: str) -> list[dict]:
    sb = get_supabase()
    try:
        resp = (
            sb.table("agent_configs")
            .select("agent_type, agent_name, is_active")
            .eq("organization_id", org_id)
            .eq("is_active", True)
            .execute()
        )
        agents = resp.data or []
        log.info("[CONFIG] Active agents for org=%s: %s", org_id, [a["agent_type"] for a in agents])
        return agents
    except Exception as exc:
        log.error("[CONFIG] FAILED to load active agents for org=%s: %s", org_id, exc)
        return []


# ── Company info ─────────────────────────────────────────────────────


async def get_company_info(org_id: str) -> Optional[dict]:
    sb = get_supabase()
    try:
        resp = (
            sb.table("company_info")
            .select("*")
            .eq("organization_id", org_id)
            .maybe_single()
            .execute()
        )
        if resp and resp.data:
            log.info("[CONFIG] Loaded company_info for org=%s — name=%s", org_id, resp.data.get("company_name", "?"))
        else:
            log.warning("[CONFIG] No company_info found for org=%s", org_id)
        return resp.data if resp else None
    except Exception as exc:
        log.error("[CONFIG] FAILED to load company_info for org=%s: %s", org_id, exc)
        return None


# ── Products / Catalog ───────────────────────────────────────────────


async def get_products(org_id: str) -> list[dict]:
    sb = get_supabase()
    try:
        resp = (
            sb.table("products")
            .select("id, name, description, unit_price, category_id, status")
            .eq("organization_id", org_id)
            .execute()
        )
        products = resp.data or []
        log.info("[CONFIG] Loaded %d products for org=%s", len(products), org_id)
        return products
    except Exception as exc:
        log.error("[CONFIG] FAILED to load products for org=%s: %s", org_id, exc)
        return []


# ── Qualification steps ─────────────────────────────────────────────


async def get_qualification_steps(org_id: str, agent_type: str = "sdr") -> list[dict]:
    sb = get_supabase()
    try:
        resp = (
            sb.table("qualification_steps")
            .select("step_order, question")
            .eq("organization_id", org_id)
            .order("step_order")
            .execute()
        )
        steps = resp.data or []
        log.info("[CONFIG] Loaded %d qualification steps for org=%s", len(steps), org_id)
        return steps
    except Exception as exc:
        log.error("[CONFIG] FAILED to load qualification_steps for org=%s: %s", org_id, exc)
        return []


# ── Quick responses (FAQ) ───────────────────────────────────────────


async def get_quick_responses(org_id: str) -> list[dict]:
    sb = get_supabase()
    try:
        resp = (
            sb.table("quick_responses")
            .select("trigger_keyword, response_text")
            .eq("organization_id", org_id)
            .execute()
        )
        faq = resp.data or []
        log.info("[CONFIG] Loaded %d quick responses for org=%s", len(faq), org_id)
        return faq
    except Exception as exc:
        log.error("[CONFIG] FAILED to load quick_responses for org=%s: %s", org_id, exc)
        return []


# ── Forbidden topics ────────────────────────────────────────────────


async def get_forbidden_topics(org_id: str) -> list[str]:
    sb = get_supabase()
    try:
        resp = (
            sb.table("forbidden_topics")
            .select("topic")
            .eq("organization_id", org_id)
            .execute()
        )
        topics = [r["topic"] for r in (resp.data or [])]
        log.info("[CONFIG] Loaded %d forbidden topics for org=%s", len(topics), org_id)
        return topics
    except Exception as exc:
        log.error("[CONFIG] FAILED to load forbidden_topics for org=%s: %s", org_id, exc)
        return []


# ── Hot lead criteria ───────────────────────────────────────────────


async def get_hot_criteria(org_id: str) -> Optional[str]:
    sb = get_supabase()
    try:
        resp = (
            sb.table("lead_hot_criteria")
            .select("criteria_description")
            .eq("organization_id", org_id)
            .execute()
        )
        rows = resp.data or []
        if not rows:
            log.info("[CONFIG] No hot criteria for org=%s", org_id)
            return None
        criteria = "\n".join(r["criteria_description"] for r in rows if r.get("criteria_description"))
        log.info("[CONFIG] Loaded %d hot criteria for org=%s", len(rows), org_id)
        return criteria
    except Exception as exc:
        log.error("[CONFIG] FAILED to load lead_hot_criteria for org=%s: %s", org_id, exc)
        return None


# ── Business hours ───────────────────────────────────────────────────


async def get_business_hours(org_id: str) -> list[dict]:
    sb = get_supabase()
    try:
        resp = (
            sb.table("business_hours")
            .select("day_of_week, is_open, open_time, close_time")
            .eq("organization_id", org_id)
            .order("day_of_week")
            .execute()
        )
        hours = resp.data or []
        log.info("[CONFIG] Loaded %d business hours rows for org=%s", len(hours), org_id)
        return hours
    except Exception as exc:
        log.error("[CONFIG] FAILED to load business_hours for org=%s: %s", org_id, exc)
        return []


async def get_business_hours_config(org_id: str) -> Optional[dict]:
    sb = get_supabase()
    try:
        resp = (
            sb.table("business_hours_config")
            .select("*")
            .eq("organization_id", org_id)
            .maybe_single()
            .execute()
        )
        if resp and resp.data:
            log.info("[CONFIG] Loaded business_hours_config for org=%s", org_id)
        return resp.data if resp else None
    except Exception as exc:
        log.error("[CONFIG] FAILED to load business_hours_config for org=%s: %s", org_id, exc)
        return None


# ── Scheduling config ───────────────────────────────────────────────


async def get_scheduling_config(org_id: str) -> Optional[dict]:
    sb = get_supabase()
    try:
        resp = (
            sb.table("scheduling_config")
            .select("*")
            .eq("organization_id", org_id)
            .maybe_single()
            .execute()
        )
        if resp and resp.data:
            log.info(
                "[CONFIG] Loaded scheduling_config for org=%s — type=%s, gcal=%s",
                org_id,
                resp.data.get("scheduling_type", "?"),
                bool(resp.data.get("google_oauth_token")),
            )
        return resp.data if resp else None
    except Exception as exc:
        log.error("[CONFIG] FAILED to load scheduling_config for org=%s: %s", org_id, exc)
        return None


async def update_scheduling_token(org_id: str, token_data: dict) -> None:
    """Update the OAuth token in scheduling_config after a refresh."""
    log.info(
        "[TOKEN] update_scheduling_token — org=%s, token_keys=%s, expiry=%s",
        org_id, list(token_data.keys()), token_data.get("expiry_date"),
    )
    sb = get_supabase()
    try:
        result = sb.table("scheduling_config").update(
            {"google_oauth_token": token_data}
        ).eq("organization_id", org_id).execute()
        rows_affected = len(result.data) if result and result.data else 0
        log.info("[TOKEN] Token saved to Supabase — org=%s, rows_affected=%d", org_id, rows_affected)
        if rows_affected == 0:
            log.warning("[TOKEN] No rows updated — scheduling_config may not exist for org %s", org_id)
    except Exception as exc:
        log.error("[TOKEN] FAILED to save token — org=%s, error=%s", org_id, exc, exc_info=True)


# ── Conversation logs ───────────────────────────────────────────────


async def save_conversation_log(data: dict) -> None:
    sb = get_supabase()
    sb.table("ai_conversation_logs").insert(data).execute()


async def get_conversation_logs(
    org_id: str,
    page: int = 1,
    limit: int = 20,
    date_from: Optional[str] = None,
) -> tuple[list[dict], int]:
    sb = get_supabase()
    query = (
        sb.table("ai_conversation_logs")
        .select("*", count="exact")
        .eq("organization_id", org_id)
        .order("created_at", desc=True)
    )
    if date_from:
        query = query.gte("created_at", date_from)
    offset = (page - 1) * limit
    query = query.range(offset, offset + limit - 1)
    resp = query.execute()
    return resp.data or [], resp.count or 0


# ── Metrics ──────────────────────────────────────────────────────────


async def get_metrics(org_id: str, date_from: str) -> dict:
    sb = get_supabase()
    logs = (
        sb.table("ai_conversation_logs")
        .select("action_taken, response_time_ms, cost_usd, message_role")
        .eq("organization_id", org_id)
        .eq("message_role", "assistant")
        .gte("created_at", date_from)
        .execute()
    ).data or []

    messages = len(logs)
    handoffs = sum(1 for l in logs if l.get("action_taken") == "handoff")
    blocked = sum(1 for l in logs if l.get("action_taken") == "blocked")
    times = [l["response_time_ms"] for l in logs if l.get("response_time_ms")]
    costs = [float(l["cost_usd"]) for l in logs if l.get("cost_usd")]

    return {
        "messages_processed": messages,
        "handoffs": handoffs,
        "blocked": blocked,
        "avg_response_time_ms": sum(times) / len(times) if times else 0,
        "cost_estimate_usd": sum(costs),
    }


# ── Deal updates ─────────────────────────────────────────────────────


async def update_deal_ai_fields(
    org_id: str, contact_phone: str, agent_type: str
) -> None:
    """Mark deals associated with this contact as AI-participated."""
    sb = get_supabase()
    # Find contact by phone
    try:
        contact = (
            sb.table("contacts")
            .select("id")
            .eq("organization_id", org_id)
            .eq("phone", contact_phone)
            .maybe_single()
            .execute()
        )
    except Exception:
        return
    if not contact or not contact.data:
        return
    contact_id = contact.data["id"]
    # Update deals linked to this contact
    sb.table("deals").update(
        {"ai_participated": True, "ai_agent_type": agent_type}
    ).eq("organization_id", org_id).eq("contact_id", contact_id).execute()


# ── Chatwoot connection lookup ────────────────────────────────────


async def get_org_by_chatwoot_account(account_id: int) -> Optional[str]:
    """Return organization_id for a given Chatwoot account_id."""
    sb = get_supabase()
    try:
        resp = (
            sb.table("chatwoot_connections")
            .select("organization_id")
            .eq("chatwoot_account_id", account_id)
            .maybe_single()
            .execute()
        )
        org_id = resp.data["organization_id"] if resp and resp.data else None
        if org_id:
            log.info("[CONFIG] Resolved chatwoot account_id=%s → org=%s", account_id, org_id)
        else:
            log.warning("[CONFIG] No org found for chatwoot account_id=%s", account_id)
        return org_id
    except Exception as exc:
        log.error("[CONFIG] FAILED to lookup org by chatwoot account %s: %s", account_id, exc)
        return None


# ── Follow-up queue ─────────────────────────────────────────────────


async def get_followup_config(org_id: str) -> Optional[dict]:
    """Get follow-up configuration for an organization."""
    sb = get_supabase()
    try:
        resp = (
            sb.table("followup_config")
            .select("*")
            .eq("organization_id", org_id)
            .maybe_single()
            .execute()
        )
        if resp and resp.data:
            log.info("[FOLLOWUP] Loaded followup_config for org=%s", org_id)
        return resp.data if resp else None
    except Exception as exc:
        log.error("[FOLLOWUP] FAILED to load followup_config for org=%s: %s", org_id, exc)
        return None


async def insert_followup(
    org_id: str,
    conversation_id: int,
    contact_phone: str,
    contact_name: str,
    template_name: str,
    template_variables: list,
    scheduled_at: str,
    metadata: dict | None = None,
) -> Optional[dict]:
    """Insert a new follow-up into the queue."""
    import json as _json

    sb = get_supabase()
    try:
        data = {
            "organization_id": org_id,
            "conversation_id": conversation_id,
            "contact_phone": contact_phone,
            "contact_name": contact_name,
            "template_name": template_name,
            "template_variables": _json.dumps(template_variables),
            "scheduled_at": scheduled_at,
            "status": "pending",
            "metadata": _json.dumps(metadata or {}),
        }
        resp = sb.table("followup_queue").insert(data).execute()
        return resp.data[0] if resp and resp.data else None
    except Exception as exc:
        log.error(
            "[FOLLOWUP] FAILED to insert followup — org=%s conv=%s template=%s: %s",
            org_id, conversation_id, template_name, exc,
        )
        return None


async def followup_exists_pending(conversation_id: int, template_name: str) -> bool:
    """Check if a pending follow-up already exists for this conversation+template."""
    sb = get_supabase()
    try:
        resp = (
            sb.table("followup_queue")
            .select("id", count="exact")
            .eq("conversation_id", conversation_id)
            .eq("template_name", template_name)
            .eq("status", "pending")
            .execute()
        )
        return (resp.count or 0) > 0
    except Exception as exc:
        log.error("[FOLLOWUP] Error checking existing followup: %s", exc)
        return False


async def cancel_followups_for_conversation(conversation_id: int) -> int:
    """Cancel all pending follow-ups for a conversation. Returns count cancelled."""
    sb = get_supabase()
    try:
        resp = (
            sb.table("followup_queue")
            .update({"status": "cancelled"})
            .eq("conversation_id", conversation_id)
            .eq("status", "pending")
            .execute()
        )
        count = len(resp.data) if resp and resp.data else 0
        return count
    except Exception as exc:
        log.error("[FOLLOWUP] FAILED to cancel followups for conv %s: %s", conversation_id, exc)
        return 0


async def get_pending_followups(now_iso: str) -> list[dict]:
    """Get all pending follow-ups that are due (scheduled_at <= now)."""
    sb = get_supabase()
    try:
        resp = (
            sb.table("followup_queue")
            .select("*")
            .eq("status", "pending")
            .lte("scheduled_at", now_iso)
            .order("scheduled_at")
            .limit(50)
            .execute()
        )
        return resp.data or []
    except Exception as exc:
        log.error("[FOLLOWUP] FAILED to get pending followups: %s", exc)
        return []


async def update_followup_status(
    followup_id: str,
    status: str,
    sent_at: str | None = None,
    error: str | None = None,
) -> None:
    """Update the status of a follow-up item."""
    sb = get_supabase()
    try:
        data: dict[str, Any] = {"status": status}
        if sent_at:
            data["sent_at"] = sent_at
        if error:
            data["metadata"] = _json_merge_error(followup_id, error)
        sb.table("followup_queue").update(data).eq("id", followup_id).execute()
    except Exception as exc:
        log.error("[FOLLOWUP] FAILED to update followup %s to %s: %s", followup_id, status, exc)


def _json_merge_error(followup_id: str, error: str) -> str:
    """Build metadata JSON with error field."""
    import json as _json
    return _json.dumps({"error": error})


async def get_latest_user_message_time(
    conversation_id: int, after_timestamp: str
) -> Optional[str]:
    """Check if a user message exists for this conversation after the given timestamp."""
    sb = get_supabase()
    try:
        resp = (
            sb.table("ai_conversation_logs")
            .select("created_at")
            .eq("conversation_id", str(conversation_id))
            .eq("message_role", "user")
            .gt("created_at", after_timestamp)
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
        if resp and resp.data:
            return resp.data[0]["created_at"]
        return None
    except Exception as exc:
        log.error("[FOLLOWUP] Error getting latest user msg for conv %s: %s", conversation_id, exc)
        return None


# ── WhatsApp credentials ────────────────────────────────────────────


async def get_whatsapp_credentials(org_id: str) -> Optional[dict]:
    """Get WhatsApp Cloud API credentials (phone_number_id + access_token) for an org.

    Reads from chatwoot_connections table which stores Meta API tokens.
    """
    sb = get_supabase()
    try:
        resp = (
            sb.table("chatwoot_connections")
            .select("whatsapp_phone_number_id, whatsapp_access_token")
            .eq("organization_id", org_id)
            .maybe_single()
            .execute()
        )
        if resp and resp.data:
            pid = resp.data.get("whatsapp_phone_number_id")
            token = resp.data.get("whatsapp_access_token")
            if pid and token:
                return {"phone_number_id": pid, "access_token": token}
            log.warning(
                "[FOLLOWUP] WhatsApp credentials incomplete for org %s — pid=%s token=%s",
                org_id, bool(pid), bool(token),
            )
        else:
            log.warning("[FOLLOWUP] No chatwoot_connections found for org %s", org_id)
        return None
    except Exception as exc:
        log.error("[FOLLOWUP] FAILED to get WhatsApp creds for org %s: %s", org_id, exc)
        return None


async def get_label_mappings(org_id: str) -> list[dict]:
    """Retorna as label_mappings da org.

    Cada linha representa uma etiqueta do Chatwoot mapeada pra uma label do CRM.
    Usada tanto pelo context_builder (popular {valid_labels} no prompt) quanto
    pelo pipeline_manager (validar stage_label antes de aplicar no Chatwoot).

    Returns:
        Lista de dicts no formato:
        [{"chatwoot_label": "01-novo-contato", "crm_label_id": "...", "auto_sync": True}, ...]
        Vazio se a org não tem mappings cadastrados.
    """
    sb_client = get_supabase()
    try:
        resp = (
            sb_client.table("label_mappings")
            .select("chatwoot_label, crm_label_id, auto_sync")
            .eq("organization_id", org_id)
            .execute()
        )
        return resp.data or []
    except Exception as exc:
        log.warning("Failed to load label_mappings for org=%s: %s", org_id, exc)
        return []


# ── Contact memory ──────────────────────────────────────────────────


async def get_contact_memory(
    org_id: str, phone_digits: str, chatwoot_contact_id: str = "",
) -> Optional[dict]:
    """Get long-term memory for a contact by org + phone (digits only).

    Falls back to chatwoot_contact_id (cw: prefix) when phone is empty.
    """
    sb = get_supabase()
    try:
        # 1) Try by phone first
        if phone_digits:
            resp = (
                sb.table("contact_memory")
                .select("*")
                .eq("organization_id", org_id)
                .eq("contact_phone", phone_digits)
                .maybe_single()
                .execute()
            )
            if resp and resp.data:
                return resp.data

        # 2) Fallback: try by chatwoot_contact_id (cw: prefix)
        if chatwoot_contact_id:
            cw_key = f"cw:{chatwoot_contact_id}"
            resp = (
                sb.table("contact_memory")
                .select("*")
                .eq("organization_id", org_id)
                .eq("contact_phone", cw_key)
                .maybe_single()
                .execute()
            )
            if resp and resp.data:
                return resp.data

        return None
    except Exception as exc:
        log.error("[MEMORY] FAILED to get contact_memory for %s: %s", phone_digits or f"cw:{chatwoot_contact_id}", exc)
        return None


async def upsert_contact_memory(
    org_id: str, phone_digits: str, data: dict,
    chatwoot_contact_id: str = "",
) -> None:
    """Insert or update contact memory (keyed on org + phone).

    Uses cw:{chatwoot_contact_id} as key when phone is empty.
    """
    import json as _json

    # Resolve the memory key: phone or cw: prefix
    memory_key = phone_digits
    if not memory_key and chatwoot_contact_id:
        memory_key = f"cw:{chatwoot_contact_id}"
    if not memory_key:
        log.warning("[MEMORY] Cannot upsert — no phone and no chatwoot_contact_id")
        return

    sb = get_supabase()
    try:
        row = {
            "organization_id": org_id,
            "contact_phone": memory_key,
        }
        for field in (
            "contact_name", "contact_company", "contact_email",
            "summary", "qualification_status",
            "last_conversation_id", "last_interaction_at",
        ):
            if field in data and data[field] is not None:
                row[field] = data[field]

        interests = data.get("interests")
        if interests is not None:
            row["interests"] = interests if isinstance(interests, list) else []

        metadata = data.get("metadata")
        if metadata is not None:
            row["metadata"] = _json.dumps(metadata) if isinstance(metadata, dict) else metadata

        sb.table("contact_memory").upsert(
            row,
            on_conflict="organization_id,contact_phone",
        ).execute()
        log.info("[MEMORY] Upserted contact_memory for %s", memory_key)
    except Exception as exc:
        log.error("[MEMORY] FAILED to upsert contact_memory for %s: %s", memory_key, exc)


async def increment_contact_conversations(
    org_id: str, phone_digits: str, chatwoot_contact_id: str = "",
) -> None:
    """Increment total_conversations and update last_interaction_at."""
    from datetime import datetime, timedelta, timezone
    BRT = timezone(timedelta(hours=-3))
    now = datetime.now(BRT).isoformat()

    # Resolve memory key
    memory_key = phone_digits
    if not memory_key and chatwoot_contact_id:
        memory_key = f"cw:{chatwoot_contact_id}"
    if not memory_key:
        return

    sb = get_supabase()
    try:
        existing = await get_contact_memory(org_id, phone_digits, chatwoot_contact_id)
        if existing:
            total = (existing.get("total_conversations") or 0) + 1
            sb.table("contact_memory").update({
                "total_conversations": total,
                "last_interaction_at": now,
            }).eq("organization_id", org_id).eq("contact_phone", memory_key).execute()
    except Exception as exc:
        log.error("[MEMORY] FAILED to increment conversations for %s: %s", memory_key, exc)


# ── Chatwoot connection (full) ─────────────────────────────────────


async def get_chatwoot_connection(org_id: str) -> Optional[dict]:
    """Get full Chatwoot connection details for an org.

    May include: chatwoot_account_id, api_access_token, base_url,
    whatsapp_phone_number_id, whatsapp_access_token.
    """
    sb = get_supabase()
    try:
        resp = (
            sb.table("chatwoot_connections")
            .select("*")
            .eq("organization_id", org_id)
            .maybe_single()
            .execute()
        )
        if resp and resp.data:
            log.info("[PIPELINE] Loaded chatwoot_connection for org=%s", org_id)
        return resp.data if resp else None
    except Exception as exc:
        log.error("[PIPELINE] FAILED to get chatwoot_connection for org=%s: %s", org_id, exc)
        return None


# ── Cached Chatwoot connection ────────────────────────────────────

import time as _time

_chatwoot_conn_cache: dict[str, tuple[Optional[dict], float]] = {}
_CHATWOOT_CACHE_TTL = 300  # 5 minutes

# ── Org default owner (cached) ────────────────────────────────────

_owner_cache: dict[str, tuple[Optional[str], float]] = {}
_OWNER_CACHE_TTL = 300  # 5 minutes


async def get_org_default_owner(org_id: str) -> Optional[str]:
    """Return user_id for auto-assignment: prefer ai_agent, fallback to org_admin.

    Cached for 5 minutes to avoid repeated queries.
    """
    now = _time.time()
    if org_id in _owner_cache:
        uid, ts = _owner_cache[org_id]
        if now - ts < _OWNER_CACHE_TTL:
            return uid

    sb = get_supabase()
    try:
        # 1) Prefer ai_agent (virtual AI user)
        resp = (
            sb.table("org_members")
            .select("user_id")
            .eq("organization_id", org_id)
            .eq("role", "ai_agent")
            .limit(1)
            .execute()
        )
        if resp and resp.data:
            uid = resp.data[0]["user_id"]
            _owner_cache[org_id] = (uid, now)
            log.info("[OWNER] AI agent owner for org=%s → %s", org_id, uid)
            return uid

        # 2) Fallback to org_admin/org_moderator
        resp = (
            sb.table("org_members")
            .select("user_id")
            .eq("organization_id", org_id)
            .in_("role", ["org_admin", "org_moderator"])
            .order("created_at")
            .limit(1)
            .execute()
        )
        uid = resp.data[0]["user_id"] if resp and resp.data else None
        _owner_cache[org_id] = (uid, now)
        if uid:
            log.info("[OWNER] Admin owner for org=%s → %s", org_id, uid)
        else:
            log.warning("[OWNER] No admin/ai_agent found for org=%s", org_id)
        return uid
    except Exception as exc:
        log.error("[OWNER] FAILED to get default owner for org=%s: %s", org_id, exc)
        _owner_cache[org_id] = (None, now)
        return None


async def get_chatwoot_connection_cached(org_id: str) -> Optional[dict]:
    """Cached version of get_chatwoot_connection (TTL 5 min)."""
    now = _time.time()
    if org_id in _chatwoot_conn_cache:
        conn, ts = _chatwoot_conn_cache[org_id]
        if now - ts < _CHATWOOT_CACHE_TTL:
            return conn

    conn = await get_chatwoot_connection(org_id)
    _chatwoot_conn_cache[org_id] = (conn, now)
    return conn


# ── Pipeline management ────────────────────────────────────────────


async def get_pipeline_stages(org_id: str, pipeline_id: str = None) -> list[dict]:
    """Get pipeline stages ordered by position.

    If pipeline_id is None, uses the org's first pipeline.
    """
    sb = get_supabase()
    try:
        if not pipeline_id:
            pipe_resp = (
                sb.table("pipelines")
                .select("id")
                .eq("organization_id", org_id)
                .order("created_at")
                .limit(1)
                .execute()
            )
            if not pipe_resp or not pipe_resp.data:
                log.warning("[PIPELINE] No pipeline found for org=%s", org_id)
                return []
            pipeline_id = pipe_resp.data[0]["id"]

        resp = (
            sb.table("pipeline_stages")
            .select("id, name, position, pipeline_id")
            .eq("pipeline_id", pipeline_id)
            .order("position")
            .execute()
        )
        stages = resp.data or []
        log.info(
            "[PIPELINE] Loaded %d stages for pipeline=%s org=%s",
            len(stages), pipeline_id, org_id,
        )
        return stages
    except Exception as exc:
        log.error("[PIPELINE] FAILED to get stages for org=%s: %s", org_id, exc)
        return []


async def find_contact_by_phone(org_id: str, phone: str) -> Optional[dict]:
    """Find contact trying multiple phone formats (exact, +/- prefix, digits suffix)."""
    import re as _re

    sb = get_supabase()
    clean = phone.strip().replace("-", "").replace(" ", "")
    digits = _re.sub(r"\D", "", clean)
    cols = "id, name, phone, chatwoot_contact_id, owner_user_id, city, campaign_context"

    try:
        # 1) Exact match
        for variant in [clean, digits]:
            resp = (
                sb.table("contacts").select(cols)
                .eq("organization_id", org_id).eq("phone", variant)
                .maybe_single().execute()
            )
            if resp and resp.data:
                return resp.data

        # 2) Try without/with + prefix
        alt = clean[1:] if clean.startswith("+") else "+" + clean
        resp = (
            sb.table("contacts").select(cols)
            .eq("organization_id", org_id).eq("phone", alt)
            .maybe_single().execute()
        )
        if resp and resp.data:
            return resp.data

        # 3) Suffix match (last 10-11 digits)
        if len(digits) >= 10:
            suffix = digits[-11:] if len(digits) >= 11 else digits[-10:]
            resp = (
                sb.table("contacts").select(cols)
                .eq("organization_id", org_id)
                .ilike("phone", f"%{suffix}%")
                .limit(1).execute()
            )
            if resp and resp.data:
                return resp.data[0]

        return None
    except Exception as exc:
        log.error("[PIPELINE] FAILED to find contact by phone=%s: %s", phone, exc)
        return None


async def find_contact_by_chatwoot_id(org_id: str, chatwoot_id: str) -> Optional[dict]:
    """Find contact by chatwoot_contact_id column."""
    if not chatwoot_id:
        return None
    sb = get_supabase()
    cid = str(chatwoot_id)
    cols = "id, name, phone, chatwoot_contact_id, owner_user_id, city, campaign_context"
    try:
        resp = (
            sb.table("contacts").select(cols)
            .eq("organization_id", org_id)
            .eq("chatwoot_contact_id", cid)
            .limit(1).execute()
        )
        if resp and resp.data:
            return resp.data[0]
        return None
    except Exception as exc:
        log.error("[PIPELINE] FAILED to find contact by chatwoot_contact_id=%s: %s", cid, exc)
        return None


async def find_contacts_by_name(org_id: str, name: str) -> list[dict]:
    """Find contacts by exact name (case-insensitive) in the org."""
    if not name or not name.strip():
        return []
    sb = get_supabase()
    cols = "id, name, phone, email, chatwoot_contact_id, owner_user_id, city, campaign_context"
    try:
        resp = (
            sb.table("contacts").select(cols)
            .eq("organization_id", org_id)
            .ilike("name", name.strip())
            .limit(10).execute()
        )
        return resp.data if resp and resp.data else []
    except Exception as exc:
        log.error("[PIPELINE] FAILED to find contacts by name='%s': %s", name, exc)
        return []


async def update_contact_fields(contact_id: str, fields: dict) -> bool:
    """Update specific fields on a contact."""
    sb = get_supabase()
    try:
        resp = sb.table("contacts").update(fields).eq("id", contact_id).execute()
        return bool(resp and resp.data)
    except Exception as exc:
        log.error("[PIPELINE] FAILED to update contact %s: %s", contact_id, exc)
        return False


_CHANNEL_LOWERCASE = {
    "WhatsApp": "whatsapp",
    "Instagram": "instagram",
    "Messenger": "messenger",
    "Site": "web",
    "Email": "email",
    "Telegram": "telegram",
    "SMS": "sms",
}


def _channel_to_lowercase(channel: str) -> str:
    """Map user-facing channel name to lowercase key for segmentation filters."""
    return _CHANNEL_LOWERCASE.get(channel, channel.lower() if channel else "")


async def create_contact(
    org_id: str, name: str, phone: str, source: str = "whatsapp",
    chatwoot_contact_id: str = "", channel: str = "WhatsApp",
    owner_user_id: str = "",
    city: str = "", state: str = "", country: str = "",
) -> Optional[dict]:
    """Create a new contact in the CRM."""
    import re as _re
    from datetime import datetime, timedelta, timezone
    BRT = timezone(timedelta(hours=-3))

    sb = get_supabase()
    digits = _re.sub(r"\D", "", phone.strip()) if phone else ""
    try:
        row: dict[str, Any] = {
            "organization_id": org_id,
            "name": name or "Sem nome",
            "phone": digits,
            "status": "lead",
            "person_type": "PF",
            "last_channel": channel,
            "channel": _channel_to_lowercase(channel),
            "last_interaction_at": datetime.now(BRT).isoformat(),
        }
        if chatwoot_contact_id:
            row["chatwoot_contact_id"] = str(chatwoot_contact_id)
        if owner_user_id:
            row["owner_user_id"] = owner_user_id
        if city:
            row["city"] = city
        if state:
            row["state"] = state
        if country:
            row["country"] = country
        resp = sb.table("contacts").insert(row).execute()
        if resp and resp.data:
            contact = resp.data[0]
            log.info(
                "[PIPELINE:CONTACT:CREATE] Contato criado: %s (phone=%s, id=%s)",
                name, digits, contact["id"],
            )
            return contact
        return None
    except Exception as exc:
        log.error("[PIPELINE] FAILED to create contact %s (%s): %s", name, phone, exc)
        return None


async def capture_contact_phone(
    org_id: str, chatwoot_contact_id: str, phone: str,
) -> bool:
    """Update phone on a contact created without one (non-WhatsApp channel).

    Also migrates the contact_memory key from cw:{id} to the real phone digits.
    """
    import re as _re
    digits = _re.sub(r"\D", "", phone)
    if not digits or not chatwoot_contact_id:
        return False

    sb = get_supabase()
    try:
        # 1) Find contact by chatwoot_contact_id
        contact = await find_contact_by_chatwoot_id(org_id, chatwoot_contact_id)
        if not contact:
            log.warning("[CAPTURE] Contact not found for chatwoot_id=%s", chatwoot_contact_id)
            return False

        # Skip if contact already has a phone
        if contact.get("phone"):
            log.info("[CAPTURE] Contact %s already has phone=%s, skipping", contact["id"], contact["phone"])
            return False

        # 2) Update contact with captured phone
        await update_contact_fields(contact["id"], {"phone": digits})
        log.info(
            "[CHANNEL:CAPTURE:UPDATE] Contact %s (cw:%s) updated with phone %s",
            contact["id"], chatwoot_contact_id, digits,
        )

        # 3) Migrate contact_memory key from cw:{id} → real phone digits
        cw_key = f"cw:{chatwoot_contact_id}"
        try:
            existing = (
                sb.table("contact_memory")
                .select("id")
                .eq("organization_id", org_id)
                .eq("contact_phone", cw_key)
                .maybe_single()
                .execute()
            )
            if existing and existing.data:
                sb.table("contact_memory").update(
                    {"contact_phone": digits}
                ).eq("id", existing.data["id"]).execute()
                log.info("[CHANNEL:CAPTURE:MEMORY] Memory key migrated: %s → %s", cw_key, digits)
        except Exception as mem_exc:
            log.warning("[CHANNEL:CAPTURE:MEMORY] Migration failed: %s", mem_exc)

        # 4) Upgrade pending chatwoot_direct follow-ups to WhatsApp templates
        try:
            pending = (
                sb.table("followup_queue")
                .select("id, template_name")
                .eq("organization_id", org_id)
                .eq("contact_phone", cw_key)
                .eq("status", "pending")
                .execute()
            )
            upgraded = 0
            template_map = {
                "__chatwoot_direct_24h": "followup_24h",
                "__chatwoot_direct_48h": "followup_48h_agendar",
                "__chatwoot_direct_7d": "reativacao_7d",
            }
            for row in (pending.data or []):
                wa_template = template_map.get(row["template_name"])
                if wa_template:
                    sb.table("followup_queue").update({
                        "contact_phone": digits,
                        "template_name": wa_template,
                    }).eq("id", row["id"]).execute()
                    upgraded += 1
            if upgraded:
                log.info(
                    "[FOLLOWUP:UPGRADE] %d follow-ups converted from chatwoot_direct to WhatsApp for cw:%s → %s",
                    upgraded, chatwoot_contact_id, digits,
                )
        except Exception as fu_exc:
            log.warning("[FOLLOWUP:UPGRADE] Failed: %s", fu_exc)

        return True
    except Exception as exc:
        log.error("[CHANNEL:CAPTURE] Failed for cw:%s phone=%s: %s", chatwoot_contact_id, phone, exc)
        return False


async def find_deal_for_contact(org_id: str, contact_id: str) -> Optional[dict]:
    """Find the most recent deal for a contact."""
    sb = get_supabase()
    try:
        resp = (
            sb.table("deals")
            .select("id, stage_id, pipeline_id, status, value")
            .eq("organization_id", org_id)
            .eq("contact_id", contact_id)
            .order("created_at", desc=True)
            .limit(1).execute()
        )
        if resp and resp.data:
            return resp.data[0]
        return None
    except Exception as exc:
        log.error("[PIPELINE] FAILED to find deal for contact=%s: %s", contact_id, exc)
        return None


async def create_deal(
    org_id: str, contact_id: str, pipeline_id: str, stage_id: str,
) -> Optional[dict]:
    """Create a new deal in the CRM pipeline."""
    sb = get_supabase()
    try:
        resp = (
            sb.table("deals")
            .insert({
                "organization_id": org_id,
                "contact_id": contact_id,
                "pipeline_id": pipeline_id,
                "stage_id": stage_id,
                "value": 0,
                "status": "open",
            })
            .execute()
        )
        if resp and resp.data:
            deal = resp.data[0]
            log.info(
                "[PIPELINE:DEAL:CREATE] Deal criado — id=%s contact=%s stage=%s",
                deal["id"], contact_id, stage_id,
            )
            return deal
        return None
    except Exception as exc:
        log.error("[PIPELINE] FAILED to create deal for contact=%s: %s", contact_id, exc)
        return None


async def update_deal_stage(deal_id: str, stage_id: str) -> bool:
    """Move a deal to a different pipeline stage."""
    sb = get_supabase()
    try:
        resp = (
            sb.table("deals")
            .update({"stage_id": stage_id})
            .eq("id", deal_id)
            .execute()
        )
        success = bool(resp and resp.data)
        if success:
            log.info("[PIPELINE] Deal %s moved to stage %s", deal_id, stage_id)
        return success
    except Exception as exc:
        log.error("[PIPELINE] FAILED to update deal %s stage: %s", deal_id, exc)
        return False


async def update_deal_lost(deal_id: str, reason: str = "unknown") -> bool:
    """Mark a deal as lost.

    Atualiza status='lost', loss_reason e closed_at.
    """
    from datetime import datetime  # padrão do arquivo: import local
    sb = get_supabase()
    try:
        resp = (
            sb.table("deals")
            .update({
                "status": "lost",
                "loss_reason": reason,
                "closed_at": datetime.utcnow().isoformat(),
            })
            .eq("id", deal_id)
            .execute()
        )
        success = bool(resp and resp.data)
        if success:
            log.info("[PIPELINE] Deal %s marked as LOST (reason=%s)", deal_id, reason)
        return success
    except Exception as exc:
        log.error("[PIPELINE] FAILED to mark deal %s as lost: %s", deal_id, exc)
        return False


async def update_deal_won(deal_id: str, reason: str = "closed") -> bool:
    """Mark a deal as won.

    Atualiza status='won', won_reason e closed_at.
    """
    from datetime import datetime  # padrão do arquivo: import local
    sb = get_supabase()
    try:
        resp = (
            sb.table("deals")
            .update({
                "status": "won",
                "won_reason": reason,
                "closed_at": datetime.utcnow().isoformat(),
            })
            .eq("id", deal_id)
            .execute()
        )
        success = bool(resp and resp.data)
        if success:
            log.info("[PIPELINE] Deal %s marked as WON (reason=%s)", deal_id, reason)
        return success
    except Exception as exc:
        log.error("[PIPELINE] FAILED to mark deal %s as won: %s", deal_id, exc)
        return False


# ── Assignment: find CRM user by email ────────────────────────────


async def find_user_id_by_email(email: str) -> Optional[str]:
    """Find a CRM user_id by email (from auth.users via org_members join)."""
    if not email:
        return None
    sb = get_supabase()
    try:
        # org_members doesn't have email, so query auth.users via Supabase Admin API
        # Since we use service_role key, we can query auth.users
        resp = sb.auth.admin.list_users()
        for user in resp:
            if getattr(user, "email", None) == email:
                return str(user.id)
        return None
    except Exception as exc:
        log.error("[ASSIGNMENT] FAILED to find user by email=%s: %s", email, exc)
        return None


async def find_contact_by_chatwoot_contact_id(
    org_id: str, chatwoot_contact_id: str,
) -> Optional[dict]:
    """Find contact by chatwoot_contact_id, returning id + name + owner_user_id."""
    if not chatwoot_contact_id:
        return None
    sb = get_supabase()
    try:
        resp = (
            sb.table("contacts")
            .select("id, name, owner_user_id")
            .eq("organization_id", org_id)
            .eq("chatwoot_contact_id", str(chatwoot_contact_id))
            .limit(1)
            .execute()
        )
        return resp.data[0] if resp and resp.data else None
    except Exception as exc:
        log.error("[ASSIGNMENT] FAILED to find contact by cw_id=%s: %s", chatwoot_contact_id, exc)
        return None
