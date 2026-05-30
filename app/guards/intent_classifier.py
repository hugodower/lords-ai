from __future__ import annotations
import re

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


def classify_message_nature(message: str) -> str:
    """Heurística PURA (sem modelo). Retorna a natureza da mensagem recebida.
    Valores: 'human' | 'auto_reply' | 'out_of_office' | 'wrong_number'.
    CONSERVADORA: só retorna algo != 'human' quando o texto é claramente
    institucional/automático. Em qualquer dúvida → 'human'.
    """
    if not message or not message.strip():
        return "human"

    msg = message.strip().lower()

    # Priority check: Signs of human conversation - these override auto-reply patterns
    human_signals = [
        r'\?',  # Contains question mark
        r'^(oi|olá|bom dia|boa tarde|boa noite)(\s|$)',  # Greetings
        r'\b(tenho interesse|quero saber|quanto custa|qual o valor|gostaria|preciso)\b',  # Interest signals
        r'\b(produto|serviço|preço|orçamento)\b',  # Product/service mentions
        r'\bquero\b',  # Intent clarification (safe, specific to human conversation)
    ]

    for pattern in human_signals:
        if re.search(pattern, msg):
            return "human"

    # Auto-reply patterns - only match clear institutional language
    auto_reply_patterns = [
        r'\bmensagem automática\b',
        r'\bresposta automática\b',
        r'\bretornaremos assim que possível\b',
        r'\bresponderemos em breve\b',
        r'\bentraremos em contato\b',
        r'\bobrigad[oa] pelo contato\b.*\bretornaremos\b',
        r'\bobrigad[oa] pela mensagem\b.*\bretorno\b',
    ]

    for pattern in auto_reply_patterns:
        if re.search(pattern, msg):
            return "auto_reply"

    # Out of office patterns
    out_of_office_patterns = [
        r'\bestamos fora do horário\b',
        r'\bfora do expediente\b',
        r'\bno momento não podemos atender\b',
        r'\bhorário de atendimento\b.*\b(encerrado|fechado)\b',
        r'\bestou de férias\b',
        r'\bausente até\b',
        r'\bfora do escritório\b',
        r'\bretorno dia\b',
        r'\bvoltarei em\b',
    ]

    for pattern in out_of_office_patterns:
        if re.search(pattern, msg):
            return "out_of_office"

    # Wrong number patterns - only clear dismissals, not explanatory context
    wrong_number_patterns = [
        r'^número errado\b',  # Starts with "número errado"
        r'^foi engano\b',     # Starts with "foi engano"
        r'\bengano\s*,?\s*(desculp|sorry)\b',
        r'\bdesvio\s+de\s+número\b',
        r'^não\s+é\s+este\s+número\b',  # Starts with clear denial
    ]

    for pattern in wrong_number_patterns:
        if re.search(pattern, msg):
            return "wrong_number"

    # Default: assume human if no clear institutional pattern
    return "human"
