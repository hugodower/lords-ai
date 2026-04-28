"""Testes para o parser de Meta Lead Ads."""
import pytest

from app.utils.meta_lead_parser import (
    parse_meta_lead_ad,
    is_likely_meta_lead_ad,
)


class TestParseMetaLeadAd:
    """Testes para a função parse_meta_lead_ad."""

    def test_parse_real_jose_vieira_payload(self):
        """Cenário real do lead Jose Vieira (caso original que motivou correção)."""
        content = """Qual dessas etapas você trabalha hoje com o gado?: Cria
Full name: Jose Vieira dos Santos
Hoje, você está buscando melhorar o desempenho do seu rebanho?: Sim, estou buscando melhorar agora
Phone number: (38) 9996-7762
City: Brasília de Minas
Hoje, o que mais tem te incomodado no desempenho do gado?: Custo alto na alimentação
Você já utiliza algum tipo de protocolo ou suplemento hoje?: Sim, já utilizo regularmente
Hoje, qual o tamanho aproximado do seu rebanho?: Até 100 cabeças"""

        result = parse_meta_lead_ad(content)

        assert result is not None
        assert result["name"] == "Jose Vieira dos Santos"
        assert result["phone"] == "(38) 9996-7762"
        assert result["city"] == "Brasília de Minas"
        assert result["email"] == ""
        # Custom attributes
        assert "Qual dessas etapas você trabalha hoje com o gado?" in result["custom_attributes"]
        assert result["custom_attributes"]["Qual dessas etapas você trabalha hoje com o gado?"] == "Cria"
        assert "Hoje, qual o tamanho aproximado do seu rebanho?" in result["custom_attributes"]

    def test_parse_minimal_payload(self):
        """Payload mínimo válido (só name + phone)."""
        content = """Full name: Maria Silva
Phone number: (11) 99999-8888"""

        result = parse_meta_lead_ad(content)

        assert result is not None
        assert result["name"] == "Maria Silva"
        assert result["phone"] == "(11) 99999-8888"

    def test_parse_with_email(self):
        """Payload com email."""
        content = """Full name: Pedro Santos
Phone number: (21) 98888-7777
Email: pedro@email.com"""

        result = parse_meta_lead_ad(content)

        assert result is not None
        assert result["email"] == "pedro@email.com"

    def test_returns_none_for_empty_content(self):
        """Conteúdo vazio retorna None."""
        assert parse_meta_lead_ad("") is None
        assert parse_meta_lead_ad(None) is None  # type: ignore

    def test_returns_none_for_normal_message(self):
        """Mensagem normal de chat NÃO é detectada como Lead Ad."""
        content = "Olá, quero saber sobre o protocolo de gado de corte"
        assert parse_meta_lead_ad(content) is None

    def test_returns_none_without_full_name(self):
        """Sem 'Full name:' retorna None."""
        content = """Phone number: (11) 99999-9999
City: São Paulo"""
        assert parse_meta_lead_ad(content) is None

    def test_returns_none_without_name_value(self):
        """'Full name:' presente mas vazio retorna None."""
        content = """Full name:
Phone number: (11) 99999-9999"""
        assert parse_meta_lead_ad(content) is None

    def test_handles_extra_whitespace(self):
        """Espaços extras são tratados corretamente."""
        content = """  Full name:   João Silva
  Phone number:   (11) 98765-4321  """

        result = parse_meta_lead_ad(content)

        assert result is not None
        assert result["name"] == "João Silva"
        assert result["phone"] == "(11) 98765-4321"

    def test_case_insensitive_keys(self):
        """Chaves são case-insensitive."""
        content = """FULL NAME: Ana Costa
PHONE NUMBER: (31) 91234-5678"""

        result = parse_meta_lead_ad(content)

        assert result is not None
        assert result["name"] == "Ana Costa"


class TestIsLikelyMetaLeadAd:
    """Testes para is_likely_meta_lead_ad."""

    def test_detects_lead_with_john_doe_sender(self):
        """Sender 'John Doe' + content com markers = é Lead Ad."""
        content = """Full name: Jose Vieira
Phone number: (38) 9996-7762"""

        assert is_likely_meta_lead_ad(content, "John Doe") is True

    def test_detects_lead_with_empty_sender(self):
        """Sender vazio + content com markers = é Lead Ad."""
        content = """Full name: Jose Vieira
Phone number: (38) 9996-7762"""

        assert is_likely_meta_lead_ad(content, "") is True

    def test_rejects_normal_user_with_real_name(self):
        """Sender com nome real NÃO é Lead Ad."""
        content = """Full name: Jose Vieira
Phone number: (38) 9996-7762"""

        assert is_likely_meta_lead_ad(content, "Jose Vieira dos Santos") is False

    def test_rejects_message_without_markers(self):
        """Mensagem normal mesmo com sender 'John Doe' NÃO é Lead Ad."""
        assert is_likely_meta_lead_ad("Olá, boa tarde!", "John Doe") is False