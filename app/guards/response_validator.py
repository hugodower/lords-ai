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
    # Skip price validation if há orçamento estruturado preenchido
    if (output.orcamento
        and output.orcamento.valor_total_brl
        and output.orcamento.valor_total_brl > 0):
        log.info(
            "[VALIDATOR] Skipping price check — "
            f"orcamento estruturado present: R$ {output.orcamento.valor_total_brl}"
        )
        # Still validate forbidden topics in text
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
        real_prices = set()
        for p in products:
            price = p.get("unit_price")
            if price is not None:
                # Normalize price to string format for comparison
                real_prices.add(f"{float(price):.2f}")
                real_prices.add(str(int(float(price))))

        for mentioned in mentioned_prices:
            # Extract numeric value
            value = re.sub(r"[R$\s.]", "", mentioned).replace(",", ".")
            try:
                val = float(value)
                val_str = f"{val:.2f}"
                val_int = str(int(val))
                if val_str not in real_prices and val_int not in real_prices:
                    log.warning(
                        "[VALIDATOR] Price %s not in product catalog", mentioned
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
