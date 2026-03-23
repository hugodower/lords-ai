from __future__ import annotations

import json
from typing import Optional

import anthropic

from app.config import settings
from app.utils.logger import get_logger

log = get_logger("claude")

_client: Optional[anthropic.Anthropic] = None


def get_claude() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic(api_key=settings.claude_api_key)
        log.info("Claude client initialized")
    return _client


async def generate_response(
    system_prompt: str,
    messages: list[dict],
    max_tokens: int = 500,
    temperature: float = 0.3,
) -> tuple[str, int]:
    """Call Claude API and return (response_text, total_tokens_used).

    Uses claude-sonnet-4-20250514 for best cost/performance ratio.
    """
    client = get_claude()
    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=max_tokens,
        temperature=temperature,
        system=system_prompt,
        messages=messages,
    )
    text = response.content[0].text
    tokens = response.usage.input_tokens + response.usage.output_tokens
    log.info("Claude response: %d tokens", tokens)
    return text, tokens


async def classify_intent(message: str) -> str:
    """Quick intent classification using Claude (max 50 tokens).

    Returns one of: normal, raiva, ameaca, urgencia_medica, assunto_juridico
    """
    client = get_claude()
    try:
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=50,
            temperature=0.0,
            system=(
                "Classifique a intenção da mensagem de um lead em EXATAMENTE uma "
                "destas categorias: normal, raiva, ameaca, urgencia_medica, assunto_juridico. "
                "Responda APENAS com a categoria, sem explicação."
            ),
            messages=[{"role": "user", "content": message}],
        )
        intent = response.content[0].text.strip().lower()
        valid = {"normal", "raiva", "ameaca", "urgencia_medica", "assunto_juridico"}
        return intent if intent in valid else "normal"
    except Exception as e:
        log.warning("Intent classification failed, defaulting to normal: %s", e)
        return "normal"
