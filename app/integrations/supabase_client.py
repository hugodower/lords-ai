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
        return resp.data if resp else None
    except Exception:
        return None


async def get_active_agents(org_id: str) -> list[dict]:
    sb = get_supabase()
    resp = (
        sb.table("agent_configs")
        .select("agent_type, agent_name, is_active")
        .eq("organization_id", org_id)
        .eq("is_active", True)
        .execute()
    )
    return resp.data or []


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
        return resp.data if resp else None
    except Exception:
        return None


# ── Products / Catalog ───────────────────────────────────────────────


async def get_products(org_id: str) -> list[dict]:
    sb = get_supabase()
    resp = (
        sb.table("products")
        .select("id, name, description, unit_price, category_id, status")
        .eq("organization_id", org_id)
        .eq("status", "active")
        .execute()
    )
    return resp.data or []


# ── Qualification steps ─────────────────────────────────────────────


async def get_qualification_steps(org_id: str, agent_type: str = "sdr") -> list[dict]:
    sb = get_supabase()
    resp = (
        sb.table("qualification_steps")
        .select("step_order, question, is_required")
        .eq("organization_id", org_id)
        .eq("agent_type", agent_type)
        .order("step_order")
        .execute()
    )
    return resp.data or []


# ── Quick responses (FAQ) ───────────────────────────────────────────


async def get_quick_responses(org_id: str) -> list[dict]:
    sb = get_supabase()
    resp = (
        sb.table("quick_responses")
        .select("trigger_keyword, response_text")
        .eq("organization_id", org_id)
        .eq("is_active", True)
        .execute()
    )
    return resp.data or []


# ── Forbidden topics ────────────────────────────────────────────────


async def get_forbidden_topics(org_id: str) -> list[str]:
    sb = get_supabase()
    resp = (
        sb.table("forbidden_topics")
        .select("topic")
        .eq("organization_id", org_id)
        .execute()
    )
    return [r["topic"] for r in (resp.data or [])]


# ── Hot lead criteria ───────────────────────────────────────────────


async def get_hot_criteria(org_id: str) -> Optional[str]:
    sb = get_supabase()
    try:
        resp = (
            sb.table("lead_hot_criteria")
            .select("criteria_description")
            .eq("organization_id", org_id)
            .maybe_single()
            .execute()
        )
        return resp.data["criteria_description"] if resp and resp.data else None
    except Exception:
        return None


# ── Business hours ───────────────────────────────────────────────────


async def get_business_hours(org_id: str) -> list[dict]:
    sb = get_supabase()
    resp = (
        sb.table("business_hours")
        .select("day_of_week, is_open, open_time, close_time")
        .eq("organization_id", org_id)
        .order("day_of_week")
        .execute()
    )
    return resp.data or []


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
        return resp.data if resp else None
    except Exception:
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
        return resp.data if resp else None
    except Exception:
        return None


async def update_scheduling_token(org_id: str, token_data: dict) -> None:
    """Update the OAuth token in scheduling_config after a refresh."""
    sb = get_supabase()
    try:
        sb.table("scheduling_config").update(
            {"google_oauth_token": token_data}
        ).eq("organization_id", org_id).execute()
    except Exception as exc:
        log.error("Failed to update scheduling token: %s", exc)


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
