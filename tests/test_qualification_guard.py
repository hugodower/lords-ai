"""
Tests for app.guards.qualification_guard.is_generic_greeting.
"""
import pytest

from app.guards.qualification_guard import is_generic_greeting


class TestGenericGreetingPositive:
    """Casos que DEVEM retornar True (saudação pura)."""

    @pytest.mark.parametrize("message", [
        "Olá",
        "Oi",
        "Opa",
        "Oiiii",
        "E aí",
        "Hey",
        "Hi",
        "Hello",
        "Bom dia",
        "Boa tarde",
        "Boa noite",
        "Tudo bem?",
        "Tudo bom",
        "td bem",
        "blz",
        "beleza",
        "Como vai?",
        "Como tá?",
    ])
    def test_simple_greeting(self, message):
        assert is_generic_greeting(message) is True, f"Expected True for {message!r}"

    @pytest.mark.parametrize("message", [
        "olá",
        "OLÁ",
        "Olá!",
        "Olá!!",
        "Olá.",
        "Olá ",
        " Olá ",
    ])
    def test_case_and_punctuation_variants(self, message):
        assert is_generic_greeting(message) is True, f"Expected True for {message!r}"

    def test_emoji_only(self):
        assert is_generic_greeting("👋") is True
        assert is_generic_greeting("😊") is True

    def test_multiline_debounced_greeting(self):
        # debounce concatena com \n
        assert is_generic_greeting("Opa\ntudo bem?") is True
        assert is_generic_greeting("Oi\nbom dia") is True


class TestGenericGreetingNegative:
    """Casos que DEVEM retornar False (tem sinal de qualificação ou conteúdo)."""

    @pytest.mark.parametrize("message", [
        "Olá, queria saber sobre tráfego pago",
        "Oi, vocês atendem clínica?",
        "preciso de ajuda urgente",
        "Bom dia, sou da loja de móveis e quero crm",
        "tudo bem? quanto custa?",
        "Olá! Vi a propaganda de vocês",
    ])
    def test_greeting_with_qualification_signal(self, message):
        assert is_generic_greeting(message) is False, f"Expected False for {message!r}"

    def test_empty_string(self):
        assert is_generic_greeting("") is False

    def test_whitespace_only(self):
        assert is_generic_greeting("   ") is False
        assert is_generic_greeting("\n\n") is False

    def test_long_message(self):
        # > 40 chars nunca é saudação pura
        long_msg = "Olá tudo bem por aí? estou interessado nos serviços"
        assert is_generic_greeting(long_msg) is False

    def test_mixed_greeting_and_content(self):
        # debounce com saudação + conteúdo deve retornar False
        assert is_generic_greeting("Oi\nquero saber sobre crm") is False
        assert is_generic_greeting("Bom dia\nvcs cobram quanto?") is False