from __future__ import annotations

import json
import pytest
from unittest.mock import AsyncMock, patch

from app.agents.support import support_agent


@pytest.mark.asyncio
class TestSupportAgent:
    async def test_process_support_message(
        self, org_id, mock_supabase, mock_chatwoot, mock_redis, mock_chroma,
    ):
        """Support agent should process a message and respond."""
        mock_supabase["get_agent_config"].return_value = {
            "id": "cfg-002",
            "organization_id": org_id,
            "agent_type": "support",
            "is_active": True,
            "agent_name": "Ana",
            "personality": "Prestativa e paciente.",
            "max_messages": 10,
            "max_response_time_seconds": 10,
            "handoff_agent_id": 42,
        }

        agent_output = json.dumps({
            "text": "Olá! Atendemos de segunda a sexta, das 8h às 18h. Posso ajudar em algo mais?",
            "action": "continue",
            "skill_used": "faq",
            "lead_temperature": "cold",
        })

        with (
            patch("app.agents.base.generate_response", new_callable=AsyncMock) as mock_claude,
            patch("app.agents.base.classify_message_intent", new_callable=AsyncMock) as mock_intent,
        ):
            mock_claude.return_value = (agent_output, 100)
            mock_intent.return_value = ("normal", None)

            result = await support_agent.process(
                org_id=org_id,
                conversation_id="conv-sup-001",
                contact_phone="+5518999999999",
                contact_name="Maria",
                message="Qual o horário de funcionamento?",
            )

        assert result.action == "continue"
        assert result.message_sent is not None
        assert result.agent_type == "support"

    async def test_handoff_on_cancellation(
        self, org_id, mock_supabase, mock_chatwoot, mock_redis, mock_chroma,
    ):
        """Support should handoff when intent detects urgency."""
        mock_supabase["get_agent_config"].return_value = {
            "id": "cfg-002",
            "organization_id": org_id,
            "agent_type": "support",
            "is_active": True,
            "agent_name": "Ana",
            "personality": "Prestativa e paciente.",
            "max_messages": 10,
            "max_response_time_seconds": 10,
            "handoff_agent_id": 42,
        }

        with patch("app.agents.base.classify_message_intent", new_callable=AsyncMock) as mock_intent:
            mock_intent.return_value = ("raiva", "Lead irritado — transferindo para atendimento humano.")

            result = await support_agent.process(
                org_id=org_id,
                conversation_id="conv-sup-002",
                contact_phone="+5518888888888",
                contact_name="João",
                message="Quero cancelar tudo! Péssimo serviço!",
            )

        assert result.action == "handoff"
