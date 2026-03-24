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
