"""Testes de regressão para o fix do bug de mensagens vazias no WhatsApp.

Bug corrigido: Ana enviava mensagens vazias quando Claude response tinha apenas tool_use blocks.

Testes obrigatórios:
- A: response só com tool_use → texto vazio + send_message não chama endpoint
- B: response com [tool_use, text] → retorna só o texto
- C: response com múltiplos text blocks → join com \n\n
- D: send_message("") → retorna error sem chamar endpoint
- E: send_message("   ") → mesmo comportamento de D (whitespace só)
"""

import pytest
from unittest.mock import Mock, AsyncMock, patch
from app.integrations.claude_client import generate_response, generate_extraction
from app.integrations.chatwoot import ChatwootClient


class MockResponse:
    """Mock da response da Anthropic API com diferentes tipos de content blocks."""

    def __init__(self, content_blocks, input_tokens=100, output_tokens=50):
        self.content = content_blocks
        self.usage = Mock()
        self.usage.input_tokens = input_tokens
        self.usage.output_tokens = output_tokens


class MockTextBlock:
    """Mock de um text block da Anthropic API."""

    def __init__(self, text):
        self.text = text
        self.type = "text"


class MockToolUseBlock:
    """Mock de um tool_use block da Anthropic API."""

    def __init__(self, name="calculator", input_data=None):
        self.type = "tool_use"
        self.name = name
        self.input = input_data or {"expression": "2+2"}
        self.id = "toolu_123"


class MockThinkingBlock:
    """Mock de um thinking block da Anthropic API."""

    def __init__(self, content="I need to think about this..."):
        self.type = "thinking"
        self.content = content


@pytest.mark.asyncio
class TestClaudeClientFix:
    """Testes para o fix dos multiple content blocks no Claude client."""

    @patch('app.integrations.claude_client.get_claude')
    async def test_A_tool_use_only_response_returns_empty_text(self, mock_get_claude):
        """Teste A: Response só com tool_use → texto vazio + warning nos logs."""
        # Setup: response com apenas tool_use block
        mock_client = Mock()
        mock_get_claude.return_value = mock_client

        tool_use_response = MockResponse([
            MockToolUseBlock("calculator", {"expression": "5*3"})
        ], output_tokens=25)

        mock_client.messages.create = Mock(return_value=tool_use_response)

        # Execute
        with patch('app.integrations.claude_client.log') as mock_log:
            text, tokens = await generate_response("test prompt", [])

            # Assert: texto vazio
            assert text == "", f"Esperado texto vazio, recebido: {text!r}"
            assert tokens == 125, f"Esperado 125 tokens (100+25), recebido: {tokens}"

            # Assert: warning foi logado
            mock_log.warning.assert_called_once()
            warning_call_args = mock_log.warning.call_args[0]
            assert "[CLAUDE:NO_TEXT_BLOCK]" in warning_call_args[0]
            assert "%d output tokens but no text block" in warning_call_args[0]
            assert warning_call_args[1] == 25  # output_tokens
            assert "tool_use" in str(warning_call_args[2])  # block types list

    @patch('app.integrations.claude_client.get_claude')
    async def test_B_mixed_response_returns_only_text(self, mock_get_claude):
        """Teste B: Response com [tool_use, text] → retorna só o texto."""
        # Setup: response mista com tool_use + text
        mock_client = Mock()
        mock_get_claude.return_value = mock_client

        mixed_response = MockResponse([
            MockToolUseBlock("calculator", {"expression": "10/2"}),
            MockTextBlock("O resultado é 5."),
            MockToolUseBlock("search", {"query": "weather"})
        ], output_tokens=40)

        mock_client.messages.create = Mock(return_value=mixed_response)

        # Execute
        text, tokens = await generate_response("test prompt", [])

        # Assert: só o texto, ignorando tool_use blocks
        assert text == "O resultado é 5.", f"Esperado apenas o texto, recebido: {text!r}"
        assert tokens == 140

    @patch('app.integrations.claude_client.get_claude')
    async def test_C_multiple_text_blocks_joined_with_double_newline(self, mock_get_claude):
        """Teste C: Response com múltiplos text blocks → join com \\n\\n."""
        # Setup: response com múltiplos text blocks
        mock_client = Mock()
        mock_get_claude.return_value = mock_client

        multi_text_response = MockResponse([
            MockTextBlock("Olá! Como posso ajudar?"),
            MockToolUseBlock("calendar", {"action": "check"}),
            MockTextBlock("Vejo que você tem uma reunião às 15h."),
            MockTextBlock("Gostaria de reagendar?")
        ], output_tokens=60)

        mock_client.messages.create = Mock(return_value=multi_text_response)

        # Execute
        text, tokens = await generate_response("test prompt", [])

        # Assert: textos unidos com \n\n
        expected = "Olá! Como posso ajudar?\n\nVejo que você tem uma reunião às 15h.\n\nGostaria de reagendar?"
        assert text == expected, f"Esperado join com \\n\\n, recebido: {text!r}"
        assert tokens == 160

    async def test_D_send_message_empty_string_returns_error(self):
        """Teste D: send_message("") → retorna error sem chamar endpoint."""
        client = ChatwootClient()

        # Execute
        result = await client.send_message("123", "")

        # Assert: retorna erro
        assert "error" in result, f"Esperado erro, recebido: {result}"
        assert "Empty or invalid message content" in result["error"]

    async def test_E_send_message_whitespace_only_returns_error(self):
        """Teste E: send_message("   ") → mesmo comportamento de D (whitespace só)."""
        client = ChatwootClient()

        # Test cases: diferentes tipos de whitespace
        whitespace_inputs = [
            "   ",        # espaços
            "\t\t",       # tabs
            "\n\n",       # newlines
            " \t\n ",     # mixed whitespace
        ]

        for whitespace in whitespace_inputs:
            # Execute
            result = await client.send_message("123", whitespace)

            # Assert: retorna erro
            assert "error" in result, f"Esperado erro para {whitespace!r}, recebido: {result}"
            assert "Empty or invalid message content" in result["error"]

    async def test_F_send_message_none_returns_error(self):
        """Teste extra: send_message(None) → retorna error."""
        client = ChatwootClient()

        # Execute
        result = await client.send_message("123", None)

        # Assert: retorna erro
        assert "error" in result, f"Esperado erro, recebido: {result}"
        assert "Empty or invalid message content" in result["error"]

    async def test_G_send_message_non_string_returns_error(self):
        """Teste extra: send_message(123) → retorna error."""
        client = ChatwootClient()

        # Execute
        result = await client.send_message("123", 123)

        # Assert: retorna erro
        assert "error" in result, f"Esperado erro, recebido: {result}"
        assert "Empty or invalid message content" in result["error"]

    @patch('app.integrations.claude_client.get_claude')
    async def test_H_generate_extraction_also_fixed(self, mock_get_claude):
        """Teste extra: generate_extraction também aplica o mesmo fix."""
        # Setup: response com tool_use + text no Haiku
        mock_client = Mock()
        mock_get_claude.return_value = mock_client

        extraction_response = MockResponse([
            MockToolUseBlock("extract", {"field": "name"}),
            MockTextBlock("João Silva")
        ], output_tokens=15)

        mock_client.messages.create = Mock(return_value=extraction_response)

        # Execute
        text, tokens = await generate_extraction("extract name from text")

        # Assert: só o texto
        assert text == "João Silva", f"Esperado apenas texto, recebido: {text!r}"
        assert tokens == 115

    @patch('app.integrations.claude_client.get_claude')
    async def test_I_empty_response_no_warning_when_no_output_tokens(self, mock_get_claude):
        """Teste edge case: resposta vazia sem output tokens não deve gerar warning."""
        # Setup: response vazia sem output tokens
        mock_client = Mock()
        mock_get_claude.return_value = mock_client

        empty_response = MockResponse([], input_tokens=50, output_tokens=0)
        mock_client.messages.create = Mock(return_value=empty_response)

        # Execute
        with patch('app.integrations.claude_client.log') as mock_log:
            text, tokens = await generate_response("test prompt", [])

            # Assert: texto vazio, mas sem warning (pois output_tokens=0)
            assert text == ""
            assert tokens == 50
            mock_log.warning.assert_not_called()

    @patch('app.integrations.claude_client.get_claude')
    async def test_J_text_blocks_with_empty_content_ignored(self, mock_get_claude):
        """Teste edge case: text blocks com conteúdo vazio são ignorados."""
        # Setup: response com text blocks vazios e válidos
        mock_client = Mock()
        mock_get_claude.return_value = mock_client

        mixed_response = MockResponse([
            MockTextBlock(""),  # vazio - deve ser ignorado
            MockTextBlock("Olá!"),
            MockTextBlock("   "),  # apenas espaços - deve ser ignorado
            MockTextBlock("Como vai?"),
            MockTextBlock("")  # vazio - deve ser ignorado
        ])

        mock_client.messages.create = Mock(return_value=mixed_response)

        # Execute
        text, tokens = await generate_response("test prompt", [])

        # Assert: apenas textos não-vazios são incluídos
        assert text == "Olá!\n\nComo vai?", f"Esperado apenas textos válidos, recebido: {text!r}"


if __name__ == "__main__":
    pytest.main([__file__])