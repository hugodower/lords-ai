from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Optional

from app.memory.redis_store import get_conversation_metadata, get_conversation_history
from app.utils.logger import get_logger

log = get_logger("autonomy_limit")

MAX_CONVERSATION_MINUTES = 30


@dataclass
class AutonomyCheck:
    should_handoff: bool
    reason: Optional[str] = None


async def check_autonomy_limit(
    conversation_id: str,
    max_messages: int = 10,
) -> AutonomyCheck:
    """Check if the AI should hand off to a human based on autonomy limits."""
    history = await get_conversation_history(conversation_id)
    metadata = await get_conversation_metadata(conversation_id)

    if not history:
        return AutonomyCheck(False)

    # Count AI messages
    ai_messages = [m for m in history if m["role"] == "assistant"]

    # 1. Max messages without handoff
    if len(ai_messages) >= max_messages:
        log.warning(
            "[AUTONOMY] Conv %s hit max messages (%d)",
            conversation_id,
            max_messages,
        )
        return AutonomyCheck(
            True,
            f"Limite de {max_messages} mensagens atingido sem resolução.",
        )

    # 2. Lead not responding — last 2 messages are from AI
    if len(history) >= 2:
        last_two = history[-2:]
        if all(m["role"] == "assistant" for m in last_two):
            log.warning("[AUTONOMY] Conv %s: lead not responding", conversation_id)
            return AutonomyCheck(
                True,
                "Lead não respondeu às últimas 2 mensagens da IA.",
            )

    # 3. Conversation too long (> 30 min without progress)
    started_at = metadata.get("started_at")
    if started_at:
        elapsed_min = (time.time() - float(started_at)) / 60
        if elapsed_min > MAX_CONVERSATION_MINUTES:
            log.warning(
                "[AUTONOMY] Conv %s running for %.0f min", conversation_id, elapsed_min
            )
            return AutonomyCheck(
                True,
                f"Conversa ativa há {int(elapsed_min)} minutos sem resolução.",
            )

    # 4. AI repeating itself — same response twice
    if len(ai_messages) >= 2:
        if ai_messages[-1]["content"] == ai_messages[-2]["content"]:
            log.warning("[AUTONOMY] Conv %s: AI repeating itself", conversation_id)
            return AutonomyCheck(
                True,
                "IA repetiu a mesma resposta — possível loop.",
            )

    return AutonomyCheck(False)
