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


def extract_product_prices(text: str) -> list[tuple[str, float]]:
    """
    Retorna lista de (produto_mencionado, preço_associado).
    Só retorna R$ que estão a ≤100 chars de uma menção de produto.
    """
    PRODUCT_PATTERNS = [
        r"Multiplica[çc][ãa]o\s*(?:de\s*)?(\d+)\s*kg",  # "Multiplicação 10kg", "Multiplicação de 20 kg"
        r"Bovnance(?:\s*\d+\s*g)?",                       # "Bovnance" ou "Bovnance 80g"
        r"Probimais\s*R?",                                # "Probimais R"
        r"MultSacch",                                     # "MultSacch"
        r"saco\s*(?:de\s*)?(\d+)\s*kg",                  # "saco 10kg", "saco de 20 kg"
        r"embalagem\s*(?:de\s*)?(\d+)\s*kg",             # "embalagem 10kg"
    ]

    PRICE_PATTERN = re.compile(r"R\$\s*([\d.,]+)")

    product_prices = []
    for pattern in PRODUCT_PATTERNS:
        for product_match in re.finditer(pattern, text, re.IGNORECASE):
            # Janela ±100 chars
            start = max(0, product_match.start() - 100)
            end = min(len(text), product_match.end() + 100)
            window = text[start:end]

            for price_match in PRICE_PATTERN.finditer(window):
                price_str = price_match.group(1).replace(".", "").replace(",", ".")
                try:
                    price_val = float(price_str)
                    product_prices.append((product_match.group(0), price_val))
                except ValueError:
                    pass

    return product_prices


def _is_valid_product_price(price: float, catalog_prices: list[float]) -> bool:
    """
    Valida se preço é legítimo baseado no catálogo.
    Aceita: exatos, descontos 15%, múltiplos, e somas de até 2 SKUs.
    """
    # Match exato
    for catalog_price in catalog_prices:
        if abs(price - catalog_price) < 0.01:
            return True

    # Desconto legítimo 15%
    for catalog_price in catalog_prices:
        if catalog_price * 0.85 <= price <= catalog_price:
            return True

    # Múltiplos exatos (2 a 10x do mesmo SKU)
    for catalog_price in catalog_prices:
        for multiplier in range(2, 11):
            if abs(price - catalog_price * multiplier) < 0.50:
                return True

    # Soma de até 2 SKUs diferentes (ex: 2×20kg + 1×10kg)
    for p1 in catalog_prices:
        for p2 in catalog_prices:
            for n1 in range(1, 11):
                for n2 in range(1, 11):
                    if abs(price - (p1 * n1 + p2 * n2)) < 0.50:
                        return True

    return False


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

    # 3. Check prices — validate only product-associated prices (context-based)
    if products:
        catalog_prices = []
        for p in products:
            price = p.get("unit_price")
            if price is not None:
                catalog_prices.append(float(price))

        if catalog_prices:
            # Extract only prices associated with product mentions
            product_prices = extract_product_prices(text)

            if not product_prices:
                # No product-associated prices found — text only has calculated values
                log.info("[VALIDATOR] No product-associated prices found, skipping price validation")
            else:
                max_catalog_price = max(catalog_prices)

                for product, price in product_prices:
                    # _is_valid_product_price já cobre: exato, desconto 15%, múltiplos 2-10x,
                    # somas de até 2 SKUs (1-10 cada). Qualquer valor acima disso já
                    # retorna False naturalmente, então check de "above max × 1.5" é
                    # redundante e bloqueia múltiplos legítimos (ex: R$ 1.080,80 = 2 sacos 20kg).
                    if not _is_valid_product_price(price, catalog_prices):
                        log.warning(
                            "[VALIDATOR] blocked_price: R$ %.2f invalid for product %s",
                            price, product
                        )
                        return ValidationResult(
                            False,
                            f"Preço inválido R$ {price:.2f} associado a {product}",
                            "blocked_price",
                        )

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
