"""Fase 1b — per-org model/params via agent_configs.

Invariante central: com as 4 colunas NULL (estado logo após a migration, antes de
alguém setar qualquer override), a resolução devolve os defaults do código e o
request que sai do provider é byte-idêntico ao comportamento pré-Fase-1b:
provider=anthropic, model=claude-sonnet-4-6, temperature=0.3, max_tokens=500.

Cobre também os dois gotchas obrigatórios da resolução:
  - temperature/max_tokens com checagem `is None` (0.0 é falsy — não pode virar default)
  - NUMERIC volta do supabase como Decimal/str → cast float()/int()
"""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from app.config import settings
from app.integrations.claude_client import generate_response
from app.integrations.providers.base import CompletionResult
from app.integrations.providers.factory import resolve_model_params

# Defaults do código que o estado NULL deve reproduzir.
EXPECTED_PROVIDER = "anthropic"
EXPECTED_MODEL = "claude-sonnet-4-6"
EXPECTED_TEMPERATURE = 0.3
EXPECTED_MAX_TOKENS = 500


def _null_config() -> dict:
    """agent_config como volta do SELECT * logo após a migration:
    as 4 colunas presentes, todas com valor None."""
    return {
        "id": "cfg-001",
        "organization_id": "org-1",
        "agent_type": "sdr",
        "agent_name": "Ana",
        "llm_provider": None,
        "model": None,
        "model_temperature": None,
        "model_max_tokens": None,
    }


class TestSettingsDefaults:
    def test_centralized_defaults_match_legacy_literals(self):
        # Os literais 0.3/500 que viviam em base.py agora moram em settings —
        # têm que ser exatamente os mesmos valores.
        assert settings.claude_temperature_agent == EXPECTED_TEMPERATURE
        assert settings.claude_max_tokens_agent == EXPECTED_MAX_TOKENS
        # Sanidade do default de produção do modelo de geração.
        assert settings.claude_model_agent == EXPECTED_MODEL


class TestResolveModelParams:
    def test_all_null_resolves_to_code_defaults(self):
        r = resolve_model_params(_null_config())
        assert r.provider == EXPECTED_PROVIDER
        assert r.model == settings.claude_model_agent == EXPECTED_MODEL
        assert r.temperature == EXPECTED_TEMPERATURE
        assert r.max_tokens == EXPECTED_MAX_TOKENS

    def test_missing_keys_resolve_to_defaults(self):
        # Config legado, sem nenhuma das colunas novas → mesmos defaults.
        r = resolve_model_params({"agent_name": "Ana"})
        assert (r.provider, r.model, r.temperature, r.max_tokens) == (
            EXPECTED_PROVIDER,
            EXPECTED_MODEL,
            EXPECTED_TEMPERATURE,
            EXPECTED_MAX_TOKENS,
        )

    def test_none_config_resolves_to_defaults(self):
        r = resolve_model_params(None)
        assert r.model == EXPECTED_MODEL
        assert r.temperature == EXPECTED_TEMPERATURE
        assert r.max_tokens == EXPECTED_MAX_TOKENS

    def test_temperature_zero_is_respected(self):
        # GOTCHA: 0.0 é falsy — `or` cairia no default. Deve ser preservado.
        cfg = _null_config()
        cfg["model_temperature"] = Decimal("0.0")
        r = resolve_model_params(cfg)
        assert r.temperature == 0.0
        assert isinstance(r.temperature, float)

    def test_numeric_decimal_cast_to_float(self):
        # GOTCHA: NUMERIC volta como Decimal.
        cfg = _null_config()
        cfg["model_temperature"] = Decimal("0.70")
        r = resolve_model_params(cfg)
        assert r.temperature == 0.7
        assert isinstance(r.temperature, float)

    def test_string_values_cast(self):
        cfg = _null_config()
        cfg["model_temperature"] = "0.5"
        cfg["model_max_tokens"] = "800"
        r = resolve_model_params(cfg)
        assert r.temperature == 0.5 and isinstance(r.temperature, float)
        assert r.max_tokens == 800 and isinstance(r.max_tokens, int)

    def test_overrides_respected(self):
        cfg = _null_config()
        cfg["model"] = "claude-opus-4-8"
        cfg["model_max_tokens"] = 1000
        r = resolve_model_params(cfg)
        assert r.model == "claude-opus-4-8"
        assert r.max_tokens == 1000

    def test_unsupported_provider_falls_back_to_anthropic(self):
        cfg = _null_config()
        cfg["llm_provider"] = "openai"
        r = resolve_model_params(cfg)
        assert r.provider == "anthropic"


@pytest.mark.asyncio
class TestByteIdenticalRequest:
    async def test_null_config_produces_unchanged_request(self):
        """Espelha o wiring de base.py: resolve params do config NULL e chama
        generate_response. O request que chega no provider tem que ser idêntico
        ao pré-Fase-1b (sonnet-4-6, 0.3, 500)."""
        resolved = resolve_model_params(_null_config())

        fake_provider = MagicMock()
        fake_provider.complete.return_value = CompletionResult(
            text="ok", input_tokens=10, output_tokens=5
        )

        with patch("app.integrations.claude_client._provider", fake_provider):
            text, tokens = await generate_response(
                system_prompt="sys",
                messages=[{"role": "user", "content": "oi"}],
                model=resolved.model,
                max_tokens=resolved.max_tokens,
                temperature=resolved.temperature,
            )

        assert text == "ok"
        assert tokens == 15
        fake_provider.complete.assert_called_once()
        kwargs = fake_provider.complete.call_args.kwargs
        assert kwargs["model"] == EXPECTED_MODEL
        assert kwargs["temperature"] == EXPECTED_TEMPERATURE
        assert kwargs["max_tokens"] == EXPECTED_MAX_TOKENS


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
