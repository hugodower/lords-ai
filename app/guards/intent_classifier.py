from __future__ import annotations

from app.integrations.claude_client import classify_intent
from app.utils.logger import get_logger

log = get_logger("intent_classifier")

# Intents that trigger immediate handoff
HANDOFF_INTENTS = {"raiva", "ameaca", "urgencia_medica", "assunto_juridico"}

HANDOFF_NOTES = {
    "raiva": "Lead irritado — transferindo para atendimento humano.",
    "ameaca": "Lead fez ameaça — transferindo para atendimento humano.",
    "urgencia_medica": "Possível urgência médica — transferindo para atendimento humano.",
    "assunto_juridico": "Assunto jurídico detectado — transferindo para atendimento humano.",
}


async def classify_message_intent(message: str) -> tuple[str, str | None]:
    """Classify message intent.

    Returns (intent, handoff_note).
    handoff_note is None if the message is normal.
    """
    intent = await classify_intent(message)
    log.info("Intent classified: %s", intent)

    if intent in HANDOFF_INTENTS:
        return intent, HANDOFF_NOTES[intent]

    return intent, None
