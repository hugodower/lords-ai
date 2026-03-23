from __future__ import annotations

from app.integrations.supabase_client import save_conversation_log
from app.utils.logger import get_logger

log = get_logger("history")


async def log_interaction(
    org_id: str,
    conversation_id: str,
    contact_phone: str,
    contact_name: str,
    agent_type: str,
    message_role: str,
    message_text: str,
    skill_used: str | None = None,
    action_taken: str | None = None,
    validation_result: str | None = None,
    tokens_used: int | None = None,
    cost_usd: float | None = None,
    response_time_ms: int | None = None,
) -> None:
    """Save a conversation log entry to Supabase."""
    data = {
        "organization_id": org_id,
        "conversation_id": conversation_id,
        "contact_phone": contact_phone,
        "contact_name": contact_name,
        "agent_type": agent_type,
        "message_role": message_role,
        "message_text": message_text,
        "skill_used": skill_used,
        "action_taken": action_taken,
        "validation_result": validation_result,
        "tokens_used": tokens_used,
        "cost_usd": cost_usd,
        "response_time_ms": response_time_ms,
    }
    try:
        await save_conversation_log(data)
        log.info(
            "Logged %s message for conv %s (action=%s)",
            message_role, conversation_id, action_taken,
        )
    except Exception as e:
        log.error("Failed to log interaction: %s", e)
