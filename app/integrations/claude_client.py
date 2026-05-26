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
    try:
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=max_tokens,
            temperature=temperature,
            system=system_prompt,
            messages=messages,
            timeout=60.0,
        )
    except anthropic.APITimeoutError as exc:
        log.error(
            "[CLAUDE] API timeout after 60s — re-raising for upstream handling"
        )
        raise
    # Extract and concatenate all text blocks, ignore tool_use/thinking/etc
    text_blocks = []
    for block in response.content:
        if hasattr(block, 'text') and block.text and block.text.strip():
            text_blocks.append(block.text)
    text = "\n\n".join(text_blocks).strip()

    # Diagnostic logging for tool_use-only responses
    if not text and response.usage.output_tokens > 0:
        log.warning(
            "[CLAUDE:NO_TEXT_BLOCK] Response had %d output tokens but no text block. "
            "Likely tool_use-only response. Block types: %s",
            response.usage.output_tokens,
            [getattr(b, 'type', type(b).__name__) for b in response.content]
        )

    tokens = response.usage.input_tokens + response.usage.output_tokens
    log.info("Claude response: %d tokens", tokens)
    return text, tokens


async def generate_extraction(
    prompt: str,
    max_tokens: int = 300,
) -> tuple[str, int]:
    """Call Claude Haiku for cheap structured extraction (memory summaries).

    Uses claude-haiku-4-5-20251001 to minimize cost.
    """
    client = get_claude()
    try:
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=max_tokens,
            temperature=0.0,
            messages=[{"role": "user", "content": prompt}],
            timeout=60.0,
        )
    except anthropic.APITimeoutError as exc:
        log.error(
            "[CLAUDE] API timeout after 60s — re-raising for upstream handling"
        )
        raise
    # Extract and concatenate all text blocks, ignore tool_use/thinking/etc
    text_blocks = []
    for block in response.content:
        if hasattr(block, 'text') and block.text and block.text.strip():
            text_blocks.append(block.text)
    text = "\n\n".join(text_blocks).strip()

    # Diagnostic logging for tool_use-only responses
    if not text and response.usage.output_tokens > 0:
        log.warning(
            "[CLAUDE:NO_TEXT_BLOCK] Response had %d output tokens but no text block. "
            "Likely tool_use-only response. Block types: %s",
            response.usage.output_tokens,
            [getattr(b, 'type', type(b).__name__) for b in response.content]
        )

    tokens = response.usage.input_tokens + response.usage.output_tokens
    log.info("Haiku extraction: %d tokens", tokens)
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
            timeout=60.0,
        )
        # Extract and concatenate all text blocks, ignore tool_use/thinking/etc
        text_blocks = []
        for block in response.content:
            if hasattr(block, 'text') and block.text:
                text_blocks.append(block.text)
        intent_text = "\n\n".join(text_blocks).strip()
        intent = intent_text.strip().lower()
        valid = {"normal", "raiva", "ameaca", "urgencia_medica", "assunto_juridico"}
        return intent if intent in valid else "normal"
    except Exception as e:
        log.warning("Intent classification failed, defaulting to normal: %s", e)
        return "normal"
