from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from app.models.schemas import AgentOutput

from app.utils.logger import get_logger

log = get_logger("response_validator")

# Words that indicate forbidden promises
PROMISE_WORDS = [
    "garanto",
    "prometo",
    "certeza absoluta",
    "desconto de",
    "com certeza",
    "100% garantido",
    "garantia total",
]

# Aggressive or inappropriate tone
INAPPROPRIATE_WORDS = [
    "idiota",
    "burro",
    "imbecil",
    "estúpido",
    "otário",
    "merda",
    "porra",
    "caralho",
    "puta",
    "querida",  # can be condescending
    "amor",  # too intimate for business
    "meu bem",
    "gostosa",
    "gato",
    "linda",
]


@dataclass
class ValidationResult:
    passed: bool
    reason: Optional[str] = None
    check_name: Optional[str] = None


def _validate_forbidden_only(text: str, forbidden_topics: list[str]) -> ValidationResult:
    """Validate only forbidden topics and inappropriate content, skip price validation."""
    if not text or len(text.strip()) < 5:
        return ValidationResult(False, "Resposta vazia ou muito curta", "too_short")

    if len(text) > 1500:
        return ValidationResult(False, "Resposta muito longa (>1500 chars)", "too_long")

    text_lower = text.lower()

    # Check forbidden promises
    for word in PROMISE_WORDS:
        if word in text_lower:
            log.warning("[VALIDATOR] Forbidden promise word: %s", word)
            return ValidationResult(
                False,
                f"Resposta contém promessa proibida: '{word}'",
                "blocked_promise",
            )

    # Check forbidden topics
    for topic in forbidden_topics:
        if topic.lower() in text_lower:
            log.warning("[VALIDATOR] Forbidden topic: %s", topic)
            return ValidationResult(
                False,
                f"Resposta menciona tópico proibido: '{topic}'",
                "blocked_forbidden",
            )

    # Check inappropriate tone
    for word in INAPPROPRIATE_WORDS:
        if word in text_lower:
            log.warning("[VALIDATOR] Inappropriate word: %s", word)
            return ValidationResult(
                False,
                f"Resposta contém linguagem inadequada: '{word}'",
                "blocked_tone",
            )

    return ValidationResult(True)


def validate_response(
    output: "AgentOutput",
    products: list[dict],
    forbidden_topics: list[str],
) -> ValidationResult:
    """Validate agent response before sending to the lead.

    Returns ValidationResult with passed=True if OK, or passed=False with reason.
    """
    # BYPASS DE VALIDAÇÃO DE PREÇO — duas condições aceitas:
    #
    # 1. valor_total_brl preenchido E > 0 (orçamento completo)
    # 2. produto + n_animais preenchidos E n_animais > 0 (orçamento parcial)
    #
    # Razão: Ana às vezes preenche orcamento sem valor_total_brl
    # (esquece um campo). Bypass aceita quando há intenção clara
    # de cotação estruturada, mesmo que incompleta.
    #
    # Proteção mantida: se Ana mencionar R$ no text SEM nenhum
    # campo de orcamento, validação rigorosa ainda dispara.

    has_full_orcamento = (
        output.orcamento
        and output.orcamento.valor_total_brl
        and output.orcamento.valor_total_brl > 0
    )

    has_partial_orcamento = (
        output.orcamento
        and output.orcamento.produto
        and output.orcamento.n_animais
        and output.orcamento.n_animais > 0
    )

    if has_full_orcamento or has_partial_orcamento:
        bypass_reason = "full" if has_full_orcamento else "partial (produto+n_animais)"
        log.info(
            "[VALIDATOR] price check bypassed (%s): produto=%s n_animais=%s valor=%s",
            bypass_reason,
            output.orcamento.produto,
            output.orcamento.n_animais,
            output.orcamento.valor_total_brl
        )
        return _validate_forbidden_only(output.text, forbidden_topics)

    text = output.text

    # 1. Empty or too short
    if not text or len(text.strip()) < 5:
        log.warning("[VALIDATOR] Response too short: %d chars", len(text) if text else 0)
        return ValidationResult(False, "Resposta vazia ou muito curta", "too_short")

    # 2. Too long
    if len(text) > 1500:
        log.warning("[VALIDATOR] Response too long: %d chars", len(text))
        return ValidationResult(False, "Resposta muito longa (>1500 chars)", "too_long")

    text_lower = text.lower()

    # 3. Check prices — extract numbers that look like prices
    price_pattern = r"R\$\s*[\d.,]+"
    mentioned_prices = re.findall(price_pattern, text)
    if mentioned_prices and products:
        catalog_prices = []
        for p in products:
            price = p.get("unit_price")
            if price is not None:
                catalog_prices.append(float(price))

        if catalog_prices:
            min_catalog_price = min(catalog_prices)
            max_catalog_price = max(catalog_prices)

            for mentioned in mentioned_prices:
                # Extract numeric value
                value = re.sub(r"[R$\s.]", "", mentioned).replace(",", ".")
                try:
                    val = float(value)

                    # Allow exact matches first
                    exact_match = any(
                        abs(val - catalog_price) < 0.01 for catalog_price in catalog_prices
                    )
                    if exact_match:
                        continue

                    # Allow legitimate discounts: within 15% below any catalog price
                    discount_match = any(
                        catalog_price * 0.85 <= val <= catalog_price
                        for catalog_price in catalog_prices
                    )
                    if discount_match:
                        continue

                    # Allow derived small values (per-day, per-month costs)
                    # If mentioned price is less than 1/4 of smallest catalog price
                    if val < min_catalog_price * 0.25:
                        continue

                    # Block prices clearly above catalog max (hallucination/inflation)
                    if val > max_catalog_price:
                        log.warning(
                            "[VALIDATOR] blocked_price: R$ %.2f above catalog max R$ %.2f",
                            val, max_catalog_price
                        )
                        return ValidationResult(
                            False,
                            f"Preço mencionado ({mentioned}) acima do catálogo",
                            "blocked_price",
                        )

                    # Block other invalid prices (between min_catalog/4 and min_catalog*0.85)
                    log.warning(
                        "[VALIDATOR] blocked_price: R$ %.2f not in valid range", val
                    )
                    return ValidationResult(
                        False,
                        f"Preço mencionado ({mentioned}) não encontrado no catálogo",
                        "blocked_price",
                    )

                except ValueError:
                    pass

    # 4. Forbidden promises
    for word in PROMISE_WORDS:
        if word in text_lower:
            log.warning("[VALIDATOR] Forbidden promise word: %s", word)
            return ValidationResult(
                False,
                f"Resposta contém promessa proibida: '{word}'",
                "blocked_promise",
            )

    # 5. Forbidden topics
    for topic in forbidden_topics:
        if topic.lower() in text_lower:
            log.warning("[VALIDATOR] Forbidden topic: %s", topic)
            return ValidationResult(
                False,
                f"Resposta menciona tópico proibido: '{topic}'",
                "blocked_forbidden",
            )

    # 6. Inappropriate tone
    for word in INAPPROPRIATE_WORDS:
        if word in text_lower:
            log.warning("[VALIDATOR] Inappropriate word: %s", word)
            return ValidationResult(
                False,
                f"Resposta contém linguagem inadequada: '{word}'",
                "blocked_tone",
            )

    return ValidationResult(True)
