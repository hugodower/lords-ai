from __future__ import annotations

from app.integrations.chatwoot import chatwoot_client
from app.memory.redis_store import (
    get_conversation_history,
    get_conversation_metadata,
    clear_conversation,
)
from app.utils.logger import get_logger

log = get_logger("skill:handoff")


def _build_summary(
    agent_name: str,
    contact_name: str,
    contact_phone: str,
    history: list[dict],
    reason: str,
    lead_temperature: str = "warm",
    extra_info: str | None = None,
) -> str:
    """Build a structured handoff summary for the private note."""
    msg_count = sum(1 for m in history if m["role"] == "assistant")

    temp_emoji = {"cold": "❄️", "warm": "🌡️", "hot": "🔥"}.get(lead_temperature, "🌡️")

    summary = (
        f'📋 Resumo do SDR "{agent_name}":\n'
        f"• Nome: {contact_name or 'Não informado'}\n"
        f"• Telefone: {contact_phone}\n"
        f"• Classificação: {lead_temperature.upper()} {temp_emoji}\n"
        f"• Motivo do handoff: {reason}\n"
        f"• Mensagens trocadas: {msg_count}\n"
    )

    if extra_info:
        summary += f"• Info adicional: {extra_info}\n"

    # Last few messages for context
    recent = history[-4:] if len(history) > 4 else history
    if recent:
        summary += "\n💬 Últimas mensagens:\n"
        for m in recent:
            role = "Lead" if m["role"] == "user" else "IA"
            text = m["content"][:200]
            summary += f"  {role}: {text}\n"

    return summary


async def perform_handoff(
    conversation_id: str,
    org_id: str,
    agent_config: dict,
    contact_name: str,
    contact_phone: str,
    reason: str,
    lead_temperature: str = "warm",
    extra_info: str | None = None,
) -> bool:
    """Transfer conversation to human agent with summary.

    Returns True if handoff was successful.
    """
    history = await get_conversation_history(conversation_id)
    agent_name = agent_config.get("agent_name", "Ana")
    handoff_agent_id = agent_config.get("handoff_agent_id")

    summary = _build_summary(
        agent_name=agent_name,
        contact_name=contact_name,
        contact_phone=contact_phone,
        history=history,
        reason=reason,
        lead_temperature=lead_temperature,
        extra_info=extra_info,
    )

    try:
        # Send private note with summary
        await chatwoot_client.send_private_note(conversation_id, summary)

        # Assign to human agent if configured
        if handoff_agent_id:
            await chatwoot_client.assign_agent(conversation_id, handoff_agent_id)

        # Add label
        await chatwoot_client.add_label(conversation_id, "handoff-ia")

        # Clear AI conversation state
        await clear_conversation(conversation_id)

        log.info(
            "Handoff complete: conv=%s, agent=%s, reason=%s",
            conversation_id, handoff_agent_id, reason,
        )
        return True

    except Exception as e:
        log.error("Handoff failed: %s", e)
        return False
