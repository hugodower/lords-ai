from __future__ import annotations

import json
import pytest
from unittest.mock import AsyncMock, patch

from app.agents.sdr import sdr_agent


@pytest.mark.asyncio
class TestSDRAgent:
    async def test_process_returns_response(
        self, org_id, mock_supabase, mock_chatwoot, mock_redis, mock_chroma,
    ):
        """SDR should process a message and return a valid response."""
        agent_output = json.dumps({
            "text": "Olá! Sou a Ana, da Clínica Saúde Total. Qual o seu nome completo?",
            "action": "continue",
            "skill_used": "qualify",
            "lead_temperature": "cold",
        })

        with (
            patch("app.agents.base.generate_response", new_callable=AsyncMock) as mock_claude,
            patch("app.agents.base.classify_message_intent", new_callable=AsyncMock) as mock_intent,
        ):
            mock_claude.return_value = (agent_output, 150)
            mock_intent.return_value = ("normal", None)

            result = await sdr_agent.process(
                org_id=org_id,
                conversation_id="conv-001",
                contact_phone="+5518999999999",
                contact_name="João",
                message="Olá, gostaria de saber sobre fisioterapia",
            )

        assert result.action == "continue"
        assert result.message_sent is not None
        assert "Ana" in result.message_sent
        assert result.skill_used == "qualify"
        assert result.agent_type == "sdr"

    async def test_handoff_on_anger(
        self, org_id, mock_supabase, mock_chatwoot, mock_redis, mock_chroma,
    ):
        """SDR should handoff when lead is angry."""
        with patch("app.agents.base.classify_message_intent", new_callable=AsyncMock) as mock_intent:
            mock_intent.return_value = ("raiva", "Lead irritado — transferindo para atendimento humano.")

            result = await sdr_agent.process(
                org_id=org_id,
                conversation_id="conv-002",
                contact_phone="+5518888888888",
                contact_name="Maria",
                message="Vocês são terríveis! Péssimo atendimento!",
            )

        assert result.action == "handoff"
        # Handoff should have sent private note via handoff_cw mock
        mock_chatwoot["handoff_cw"].send_private_note.assert_called_once()

    async def test_catalog_price_response(
        self, org_id, mock_supabase, mock_chatwoot, mock_redis, mock_chroma,
    ):
        """SDR should respond with real prices from catalog."""
        agent_output = json.dumps({
            "text": "A sessão de fisioterapia custa R$ 150,00 e a de RPG R$ 200,00.",
            "action": "continue",
            "skill_used": "catalog",
            "lead_temperature": "warm",
        })

        with (
            patch("app.agents.base.generate_response", new_callable=AsyncMock) as mock_claude,
            patch("app.agents.base.classify_message_intent", new_callable=AsyncMock) as mock_intent,
        ):
            mock_claude.return_value = (agent_output, 200)
            mock_intent.return_value = ("normal", None)

            result = await sdr_agent.process(
                org_id=org_id,
                conversation_id="conv-003",
                contact_phone="+5518777777777",
                contact_name="Pedro",
                message="Quanto custa a fisioterapia?",
            )

        assert result.action == "continue"
        assert "150" in result.message_sent

    async def test_blocks_invented_price(
        self, org_id, mock_supabase, mock_chatwoot, mock_redis, mock_chroma,
    ):
        """SDR should block if Claude invents a price."""
        agent_output = json.dumps({
            "text": "A fisioterapia está em promoção por R$ 89,90!",
            "action": "continue",
            "skill_used": "catalog",
            "lead_temperature": "warm",
        })

        with (
            patch("app.agents.base.generate_response", new_callable=AsyncMock) as mock_claude,
            patch("app.agents.base.classify_message_intent", new_callable=AsyncMock) as mock_intent,
        ):
            mock_claude.return_value = (agent_output, 200)
            mock_intent.return_value = ("normal", None)

            result = await sdr_agent.process(
                org_id=org_id,
                conversation_id="conv-004",
                contact_phone="+5518666666666",
                contact_name="Ana",
                message="Tem desconto?",
            )

        assert result.action == "blocked"

    async def test_after_hours_message(
        self, org_id, mock_supabase, mock_chatwoot, mock_redis, mock_chroma,
    ):
        """SDR should send after-hours message when outside business hours."""
        with (
            patch("app.agents.base.is_within_business_hours", new_callable=AsyncMock) as mock_hours,
            patch("app.agents.base.get_after_hours_response", new_callable=AsyncMock) as mock_msg,
        ):
            mock_hours.return_value = False
            mock_msg.return_value = ("Estamos fechados! Voltamos amanhã às 8h.", "reply_and_stop")

            result = await sdr_agent.process(
                org_id=org_id,
                conversation_id="conv-005",
                contact_phone="+5518555555555",
                contact_name="Carlos",
                message="Olá!",
            )

        assert result.action == "after_hours"
        assert result.skill_used == "business_hours"

    async def test_agent_not_active_is_ignored(
        self, org_id, mock_supabase, mock_chatwoot, mock_redis, mock_chroma,
    ):
        """If agent is not active, message should be ignored."""
        mock_supabase["get_agent_config"].return_value = None

        result = await sdr_agent.process(
            org_id=org_id,
            conversation_id="conv-006",
            contact_phone="+5518444444444",
            contact_name="Test",
            message="Olá",
        )

        assert result.action == "ignored"
