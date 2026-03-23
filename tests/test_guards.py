from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, patch

from app.guards.rate_limiter import check_rate_limit, reset_rate_limits
from app.guards.response_validator import validate_response


class TestRateLimiter:
    def setup_method(self):
        reset_rate_limits()

    def test_allows_normal_messages(self):
        assert check_rate_limit("+5518999999999", "Olá") is True
        assert check_rate_limit("+5518999999999", "Tudo bem?") is True

    def test_blocks_flood(self):
        phone = "+5518888888888"
        for i in range(30):
            check_rate_limit(phone, f"msg {i}")
        # 31st message should be blocked
        assert check_rate_limit(phone, "mais uma") is False

    def test_blocks_identical_spam(self):
        phone = "+5518777777777"
        msg = "compra compra compra"
        for _ in range(5):
            check_rate_limit(phone, msg)
        # 6th identical message should be blocked
        assert check_rate_limit(phone, msg) is False

    def test_different_phones_independent(self):
        for i in range(30):
            check_rate_limit("+5518111111111", f"msg {i}")
        # Different phone should still be allowed
        assert check_rate_limit("+5518222222222", "Olá") is True


class TestIntentClassifier:
    @pytest.mark.asyncio
    async def test_classifies_anger(self):
        with patch("app.guards.intent_classifier.classify_intent", new_callable=AsyncMock) as mock:
            mock.return_value = "raiva"
            from app.guards.intent_classifier import classify_message_intent
            intent, note = await classify_message_intent("Vocês são péssimos!")
            assert intent == "raiva"
            assert note is not None
            assert "irritado" in note

    @pytest.mark.asyncio
    async def test_classifies_threat(self):
        with patch("app.guards.intent_classifier.classify_intent", new_callable=AsyncMock) as mock:
            mock.return_value = "ameaca"
            from app.guards.intent_classifier import classify_message_intent
            intent, note = await classify_message_intent("Vou processar vocês!")
            assert intent == "ameaca"
            assert note is not None

    @pytest.mark.asyncio
    async def test_classifies_normal(self):
        with patch("app.guards.intent_classifier.classify_intent", new_callable=AsyncMock) as mock:
            mock.return_value = "normal"
            from app.guards.intent_classifier import classify_message_intent
            intent, note = await classify_message_intent("Olá, gostaria de saber sobre fisioterapia")
            assert intent == "normal"
            assert note is None

    @pytest.mark.asyncio
    async def test_defaults_to_normal_on_error(self):
        with patch("app.guards.intent_classifier.classify_intent", new_callable=AsyncMock) as mock:
            mock.side_effect = Exception("API error")
            from app.integrations.claude_client import classify_intent as real_classify
            # The real classify_intent has try/except
            with patch("app.integrations.claude_client.get_claude") as mock_claude:
                mock_claude.return_value.messages.create.side_effect = Exception("timeout")
                result = await real_classify("qualquer coisa")
                assert result == "normal"
