"""Testes para o sistema de name resolution status tracking."""
from unittest.mock import patch, AsyncMock
from datetime import datetime, timezone

import pytest

from app.services.conversation_state import (
    get_name_resolution_status,
    set_name_resolution_status,
    mark_as_pending_capture,
    mark_as_captured,
    should_ask_for_name,
    extract_name_from_message,
)


@pytest.mark.asyncio
class TestNameResolutionStatus:
    """Testes para tracking de status de resolução de nome."""

    async def test_get_status_default_resolved(self):
        """Status padrão deve ser 'resolved' quando não há registro."""
        with patch("app.services.conversation_state.sb.get_contact_memory", new=AsyncMock(return_value=None)):
            status = await get_name_resolution_status(
                org_id="test-org",
                contact_phone="+5511999999999"
            )
            assert status == "resolved"

    async def test_get_status_from_memory(self):
        """Deve retornar status armazenado no contact_memory."""
        mock_memory = {
            "contact_name": "Test User",
            "metadata": {
                "name_resolution_status": "pending_capture"
            }
        }

        with patch("app.services.conversation_state.sb.get_contact_memory", new=AsyncMock(return_value=mock_memory)):
            status = await get_name_resolution_status(
                org_id="test-org",
                contact_phone="+5511999999999"
            )
            assert status == "pending_capture"

    async def test_set_status_creates_memory_if_not_exists(self):
        """Deve criar contact_memory se não existir."""
        with patch("app.services.conversation_state.sb.get_contact_memory", new=AsyncMock(return_value=None)):
            with patch("app.services.conversation_state.sb.upsert_contact_memory", new=AsyncMock()) as mock_upsert:
                success = await set_name_resolution_status(
                    org_id="test-org",
                    status="pending_capture",
                    contact_phone="+5511999999999",
                    contact_name="John Doe"
                )

                assert success is True
                mock_upsert.assert_called_once()

                # Verificar estrutura dos dados passados
                call_args = mock_upsert.call_args
                data = call_args.kwargs["data"]
                assert data["contact_name"] == "John Doe"
                assert data["metadata"]["name_resolution_status"] == "pending_capture"

    async def test_set_status_invalid_status(self):
        """Deve retornar False para status inválido."""
        success = await set_name_resolution_status(
            org_id="test-org",
            status="invalid_status",
            contact_phone="+5511999999999"
        )
        assert success is False

    async def test_mark_as_pending_capture(self):
        """mark_as_pending_capture deve definir status correto."""
        with patch("app.services.conversation_state.set_name_resolution_status", new=AsyncMock(return_value=True)) as mock_set:
            success = await mark_as_pending_capture(
                org_id="test-org",
                contact_phone="+5511999999999",
                contact_name="John Doe"
            )

            assert success is True
            mock_set.assert_called_once_with(
                org_id="test-org",
                status="pending_capture",
                contact_phone="+5511999999999",
                chatwoot_contact_id="",
                contact_name="John Doe"
            )

    async def test_mark_as_captured_updates_chatwoot(self):
        """mark_as_captured deve atualizar status E chatwoot."""
        with patch("app.services.conversation_state.set_name_resolution_status", new=AsyncMock(return_value=True)):
            with patch("app.services.conversation_state.chatwoot_client.update_contact", new=AsyncMock(return_value={})) as mock_update:
                success = await mark_as_captured(
                    org_id="test-org",
                    captured_name="Jose Silva",
                    contact_phone="+5511999999999",
                    chatwoot_contact_id="123"
                )

                assert success is True
                mock_update.assert_called_once_with(
                    contact_id=123,
                    name="Jose Silva",
                    org_id="test-org"
                )

    async def test_should_ask_for_name_with_valid_name(self):
        """Não deve perguntar nome se já tem nome válido."""
        should_ask = await should_ask_for_name(
            org_id="test-org",
            contact_name="Jose Silva"
        )
        assert should_ask is False

    async def test_should_ask_for_name_with_john_doe(self):
        """Deve perguntar nome se contato é 'John Doe' e status é pending_capture."""
        with patch("app.services.conversation_state.get_name_resolution_status", new=AsyncMock(return_value="pending_capture")):
            should_ask = await should_ask_for_name(
                org_id="test-org",
                contact_name="John Doe"
            )
            assert should_ask is True

    async def test_should_ask_for_name_with_resolved_status(self):
        """Não deve perguntar nome se status é resolved."""
        with patch("app.services.conversation_state.get_name_resolution_status", new=AsyncMock(return_value="resolved")):
            should_ask = await should_ask_for_name(
                org_id="test-org",
                contact_name="John Doe"
            )
            assert should_ask is False


class TestExtractNameFromMessage:
    """Testes para extração de nome de mensagens."""

    def test_extract_name_simple(self):
        """Deve extrair nome simples."""
        name = extract_name_from_message("João Silva")
        assert name == "João Silva"

    def test_extract_name_with_pattern(self):
        """Deve extrair nome usando padrões comuns."""
        test_cases = [
            ("Me chamo Maria Santos", "Maria Santos"),
            ("Meu nome é Pedro Costa", "Pedro Costa"),
            ("Sou o Carlos Lima", "Carlos Lima"),
            ("Pode me chamar de Ana Souza", "Ana Souza"),
            ("Nome: Roberto Dias", "Roberto Dias"),
        ]

        for message, expected in test_cases:
            name = extract_name_from_message(message)
            assert name == expected, f"Failed for message: {message}"

    def test_extract_name_invalid_cases(self):
        """Não deve extrair nome em casos inválidos."""
        invalid_messages = [
            "123",  # Só números
            "A",    # Muito curto
            "Nome com muitas palavras demais para ser um nome real válido",  # Muito longo
            "Olá, como está?",  # Não contém nome
            "abc def ghi",  # Só letras minúsculas (não típico de nome)
        ]

        for message in invalid_messages:
            name = extract_name_from_message(message)
            assert name is None, f"Incorrectly extracted name from: {message}"

    def test_extract_name_returns_title_case(self):
        """Deve retornar nome em title case."""
        name = extract_name_from_message("MARIA DOS SANTOS")
        assert name == "Maria Dos Santos"

        name = extract_name_from_message("josé da silva")
        assert name == "José Da Silva"