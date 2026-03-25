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


# ── Contact memory ──────────────────────────────────────────────────


async def get_contact_memory(org_id: str, phone_digits: str) -> Optional[dict]:
    """Get long-term memory for a contact by org + phone (digits only)."""
    sb = get_supabase()
    try:
        resp = (
            sb.table("contact_memory")
            .select("*")
            .eq("organization_id", org_id)
            .eq("contact_phone", phone_digits)
            .maybe_single()
            .execute()
        )
        return resp.data if resp else None
    except Exception as exc:
        log.error("[MEMORY] FAILED to get contact_memory for %s: %s", phone_digits, exc)
        return None


async def upsert_contact_memory(org_id: str, phone_digits: str, data: dict) -> None:
    """Insert or update contact memory (keyed on org + phone)."""
    import json as _json

    sb = get_supabase()
    try:
        row = {
            "organization_id": org_id,
            "contact_phone": phone_digits,
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
        log.info("[MEMORY] Upserted contact_memory for %s", phone_digits)
    except Exception as exc:
        log.error("[MEMORY] FAILED to upsert contact_memory for %s: %s", phone_digits, exc)


async def increment_contact_conversations(org_id: str, phone_digits: str) -> None:
    """Increment total_conversations and update last_interaction_at."""
    from datetime import datetime, timedelta, timezone
    BRT = timezone(timedelta(hours=-3))
    now = datetime.now(BRT).isoformat()

    sb = get_supabase()
    try:
        # First check if exists
        existing = await get_contact_memory(org_id, phone_digits)
        if existing:
            total = (existing.get("total_conversations") or 0) + 1
            sb.table("contact_memory").update({
                "total_conversations": total,
                "last_interaction_at": now,
            }).eq("organization_id", org_id).eq("contact_phone", phone_digits).execute()
        # If no existing row, memory will be created later by memory_manager
    except Exception as exc:
        log.error("[MEMORY] FAILED to increment conversations for %s: %s", phone_digits, exc)
