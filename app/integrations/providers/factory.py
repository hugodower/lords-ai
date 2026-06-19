from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from app.config import settings
from app.utils.logger import get_logger

log = get_logger("claude")

# Único provider cabeado hoje. Provider alternativo e credenciais per-org são
# Fase 4 — aqui só validamos o nome e caímos no anthropic por padrão.
DEFAULT_PROVIDER = "anthropic"


@dataclass(frozen=True)
class ResolvedModelParams:
    """Params efetivos da geração após aplicar override per-org → default do código."""

    provider: str
    model: str
    temperature: float
    max_tokens: int


def resolve_model_params(agent_config: Optional[dict]) -> ResolvedModelParams:
    """Resolve provider/model/temperature/max_tokens a partir do ``agent_config``.

    Regra de fallback: valor da org (coluna em ``agent_configs``) → senão default
    do código. Com TODAS as colunas NULL (estado pós-migration, antes de alguém
    setar qualquer valor) o resultado é byte-idêntico ao comportamento
    pré-Fase-1b: ``("anthropic", settings.claude_model_agent, 0.3, 500)``.

    Args:
        agent_config: dict carregado de agent_configs (SELECT *), ou None.

    Returns:
        ResolvedModelParams com os valores efetivos.
    """
    cfg = agent_config or {}

    # Strings: empty string não é valor válido, então `or` seria suficiente —
    # mas mantemos o padrão simples e explícito.
    provider = cfg.get("llm_provider") or DEFAULT_PROVIDER
    model = cfg.get("model") or settings.claude_model_agent

    # GOTCHA 1: temperature 0.0 é falsy → `or` cairia errado no default. Tem que
    #           ser checagem `is None`.
    # GOTCHA 2: NUMERIC volta do supabase como Decimal/str → cast explícito.
    temp = cfg.get("model_temperature")
    temperature = settings.claude_temperature_agent if temp is None else float(temp)

    max_tok = cfg.get("model_max_tokens")
    max_tokens = settings.claude_max_tokens_agent if max_tok is None else int(max_tok)

    # Provider != anthropic ainda não é suportado (Fase 4). Fallback seguro com
    # aviso em vez de quebrar a geração.
    if provider != DEFAULT_PROVIDER:
        log.warning(
            "[MODEL] llm_provider=%r não suportado ainda (Fase 4); usando %s",
            provider, DEFAULT_PROVIDER,
        )
        provider = DEFAULT_PROVIDER

    # Observabilidade (só INFO, não muda comportamento): qual modelo cada org
    # usou por request. source=override quando algum param veio de agent_configs;
    # default quando tudo NULL caiu no default do código. Base pro custo da Fase 3.
    log.info(
        "[MODEL:RESOLVED] org=%s model=%s temp=%s max_tokens=%s source=%s",
        cfg.get("organization_id"), model, temperature, max_tokens,
        "override" if any(
            cfg.get(k) is not None
            for k in ("model", "model_temperature", "model_max_tokens")
        ) else "default",
    )

    return ResolvedModelParams(
        provider=provider,
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
    )
