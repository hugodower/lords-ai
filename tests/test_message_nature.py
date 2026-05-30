"""Tests for message nature classification - auto-reply detection.

CONTRATO DE SEGURANÇA: Proteger contra falsos positivos (silenciar lead real).
Prioridade: não classificar conversa humana como auto-reply.
"""
import pytest
from app.guards.intent_classifier import classify_message_nature


class TestClassifyMessageNature:
    """Test message nature classification with safety-first approach."""

    def test_clear_auto_replies_detected(self):
        """True positives: clear institutional auto-replies should be detected."""
        auto_reply_messages = [
            "Esta é uma mensagem automática. Retornaremos assim que possível.",
            "Obrigado pelo contato! Retornaremos em breve.",
            "Mensagem automática: responderemos assim que possível.",
            "Obrigada pela mensagem, entraremos em contato.",
            "Resposta automática - retorno em breve.",
            "Recebemos sua mensagem, mas retornaremos assim que possível.",  # Contains "mas" - must stay auto_reply
        ]

        for msg in auto_reply_messages:
            result = classify_message_nature(msg)
            assert result == "auto_reply", f"Message should be auto_reply: {msg!r}"

    def test_clear_out_of_office_detected(self):
        """True positives: clear out-of-office messages should be detected."""
        out_of_office_messages = [
            "Obrigado pelo contato! No momento estamos fora do horário de atendimento.",
            "Estamos fora do expediente, retorno dia 20.",
            "Estou de férias até dia 20, retorno depois.",
            "Ausente até segunda-feira.",
            "Fora do escritório até amanhã.",
            "No momento não podemos atender, voltarei em breve.",
        ]

        for msg in out_of_office_messages:
            result = classify_message_nature(msg)
            assert result == "out_of_office", f"Message should be out_of_office: {msg!r}"

    def test_clear_wrong_number_detected(self):
        """True positives: clear wrong number messages should be detected."""
        wrong_number_messages = [
            "Número errado, foi engano.",
            "Foi engano, desculpa.",
            "Engano, sorry.",
            "Não é este número.",
            "Desvio de número.",
        ]

        for msg in wrong_number_messages:
            result = classify_message_nature(msg)
            assert result == "wrong_number", f"Message should be wrong_number: {msg!r}"

    def test_human_conversations_protected_questions(self):
        """CRITICAL: Questions should always be classified as human."""
        question_messages = [
            "qual o horário de atendimento de vocês?",
            "vocês atendem fora do horário comercial?",
            "estão fora do expediente agora?",
            "qual o número correto?",
            "é mensagem automática ou não?",
        ]

        for msg in question_messages:
            result = classify_message_nature(msg)
            assert result == "human", f"Question should be human: {msg!r}"

    def test_human_conversations_protected_interest(self):
        """CRITICAL: Interest signals should always be classified as human."""
        interest_messages = [
            "oi, tenho interesse, quanto custa?",
            "quero saber mais sobre o produto",
            "gostaria de um orçamento",
            "preciso do serviço de vocês",
            "qual o valor?",
            "tenho interesse no produto",
        ]

        for msg in interest_messages:
            result = classify_message_nature(msg)
            assert result == "human", f"Interest message should be human: {msg!r}"

    def test_human_conversations_protected_greetings(self):
        """CRITICAL: Simple greetings should always be classified as human."""
        greeting_messages = [
            "bom dia",
            "oi",
            "olá",
            "boa tarde",
            "boa noite",
            "Olá!",
            "Bom dia!",
        ]

        for msg in greeting_messages:
            result = classify_message_nature(msg)
            assert result == "human", f"Greeting should be human: {msg!r}"

    def test_tricky_cases_protected(self):
        """CRITICAL: Edge cases that contain trigger words but are human conversations."""
        tricky_human_messages = [
            "acho que liguei no número errado antes, mas é esse mesmo que quero falar",
            "vocês têm mensagem automática no WhatsApp?",
            "não era engano, era isso mesmo que queria",
            "quanto tempo para retornarem o contato?",
            "vocês respondem fora do horário?",
            "qual o horário que retornam as mensagens?",
        ]

        for msg in tricky_human_messages:
            result = classify_message_nature(msg)
            assert result == "human", f"Tricky case should be human: {msg!r}"

    def test_empty_or_none_messages(self):
        """Edge case: empty messages should default to human."""
        empty_messages = ["", "   ", None]

        for msg in empty_messages:
            result = classify_message_nature(msg or "")
            assert result == "human", f"Empty message should default to human: {msg!r}"

    def test_ambiguous_cases_default_human(self):
        """SAFETY: Ambiguous cases should default to human."""
        ambiguous_messages = [
            "obrigado",  # Could be auto-reply start, but too ambiguous
            "retorno",   # Could be out-of-office, but too ambiguous
            "ok",        # Generic response
            "entendi",   # Generic acknowledgment
            "valeu",     # Casual thanks
        ]

        for msg in ambiguous_messages:
            result = classify_message_nature(msg)
            assert result == "human", f"Ambiguous case should default to human: {msg!r}"