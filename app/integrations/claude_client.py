from __future__ import annotations

from app.config import settings
from app.integrations.providers.anthropic_provider import AnthropicProvider
from app.utils.logger import get_logger

log = get_logger("claude")

# Single provider instance per process. It owns the SDK client singleton, so the
# Anthropic client is still created lazily and reused across calls — same as the
# old module-level `_client`. Swapping providers later is a one-line change here.
_provider = AnthropicProvider(api_key=settings.claude_api_key)


async def generate_response(
    system_prompt: str,
    messages: list[dict],
    max_tokens: int = 500,
    temperature: float = 0.3,
    model: str | None = None,
) -> tuple[str, int]:
    """Call Claude API and return (response_text, total_tokens_used).

    `model` defaults to settings.claude_model_agent (Sonnet) when not provided.
    Callers that resolve a per-org model (see providers/factory.py) pass it in.
    """
    result = _provider.complete(
        system=system_prompt,
        messages=messages,
        model=model or settings.claude_model_agent,
        max_tokens=max_tokens,
        temperature=temperature,
    )
    tokens = result.input_tokens + result.output_tokens
    log.info("Claude response: %d tokens", tokens)
    return result.text, tokens


async def generate_extraction(
    prompt: str,
    max_tokens: int = 300,
) -> tuple[str, int]:
    """Call Claude Haiku for cheap structured extraction (memory summaries).

    Uses settings.claude_model_intent (Haiku) to minimize cost.
    """
    result = _provider.complete(
        messages=[{"role": "user", "content": prompt}],
        model=settings.claude_model_intent,
        max_tokens=max_tokens,
        temperature=0.0,
    )
    tokens = result.input_tokens + result.output_tokens
    log.info("Haiku extraction: %d tokens", tokens)
    return result.text, tokens


async def classify_intent(message: str) -> str:
    """Quick intent classification using Claude (max 50 tokens).

    Returns one of: normal, raiva, ameaca, urgencia_medica, assunto_juridico
    """
    try:
        result = _provider.complete(
            system=(
                "Classifique a intenção da mensagem de um lead em EXATAMENTE uma "
                "destas categorias: normal, raiva, ameaca, urgencia_medica, assunto_juridico. "
                "Responda APENAS com a categoria, sem explicação."
            ),
            messages=[{"role": "user", "content": message}],
            model=settings.claude_model_intent,
            max_tokens=50,
            temperature=0.0,
        )
        intent = result.text.strip().lower()
        valid = {"normal", "raiva", "ameaca", "urgencia_medica", "assunto_juridico"}
        return intent if intent in valid else "normal"
    except Exception as e:
        log.warning("Intent classification failed, defaulting to normal: %s", e)
        return "normal"
