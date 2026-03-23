from __future__ import annotations

import pytest

from app.guards.response_validator import validate_response


PRODUCTS = [
    {"name": "Fisioterapia", "price": 150.00},
    {"name": "RPG", "price": 200.00},
    {"name": "Pilates", "price": 120.00},
]

FORBIDDEN = ["política", "religião", "concorrentes"]


class TestResponseValidator:
    def test_passes_valid_response(self):
        result = validate_response(
            "Olá! Temos sessões de fisioterapia por R$ 150,00. Posso te ajudar?",
            PRODUCTS, FORBIDDEN,
        )
        assert result.passed is True

    def test_blocks_empty_response(self):
        result = validate_response("", PRODUCTS, FORBIDDEN)
        assert result.passed is False
        assert result.check_name == "too_short"

    def test_blocks_short_response(self):
        result = validate_response("ok", PRODUCTS, FORBIDDEN)
        assert result.passed is False
        assert result.check_name == "too_short"

    def test_blocks_long_response(self):
        result = validate_response("x" * 1001, PRODUCTS, FORBIDDEN)
        assert result.passed is False
        assert result.check_name == "too_long"

    def test_blocks_invented_price(self):
        result = validate_response(
            "A fisioterapia custa R$ 99,90 por sessão!",
            PRODUCTS, FORBIDDEN,
        )
        assert result.passed is False
        assert result.check_name == "blocked_price"

    def test_allows_real_price(self):
        result = validate_response(
            "A sessão de RPG custa R$ 200,00.",
            PRODUCTS, FORBIDDEN,
        )
        assert result.passed is True

    def test_blocks_promise_word_garanto(self):
        result = validate_response(
            "Eu garanto que você vai ficar satisfeito com o nosso serviço!",
            PRODUCTS, FORBIDDEN,
        )
        assert result.passed is False
        assert result.check_name == "blocked_promise"

    def test_blocks_promise_word_desconto(self):
        result = validate_response(
            "Posso oferecer um desconto de 20% para você!",
            PRODUCTS, FORBIDDEN,
        )
        assert result.passed is False
        assert result.check_name == "blocked_promise"

    def test_blocks_forbidden_topic(self):
        result = validate_response(
            "Sobre política, acho que o governo deveria investir mais em saúde.",
            PRODUCTS, FORBIDDEN,
        )
        assert result.passed is False
        assert result.check_name == "blocked_forbidden"

    def test_blocks_inappropriate_tone(self):
        result = validate_response(
            "Você é idiota se não aceitar essa oferta!",
            PRODUCTS, FORBIDDEN,
        )
        assert result.passed is False
        assert result.check_name == "blocked_tone"

    def test_combined_real_price_but_promise(self):
        """Real price + forbidden promise = blocked."""
        result = validate_response(
            "A fisioterapia custa R$ 150,00 e eu garanto resultados!",
            PRODUCTS, FORBIDDEN,
        )
        assert result.passed is False

    def test_no_products_skips_price_check(self):
        result = validate_response(
            "Nosso serviço custa R$ 999,99 por mês.",
            [], FORBIDDEN,
        )
        assert result.passed is True

    def test_price_with_integer_match(self):
        """Price mentioned as integer should match."""
        result = validate_response(
            "A sessão custa R$ 150.",
            PRODUCTS, FORBIDDEN,
        )
        assert result.passed is True
