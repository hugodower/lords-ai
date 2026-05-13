"""Testes para diferenciação de tom por canal."""
import pytest

from app.guards.context_builder import _detect_inbox_origin


class TestInboxOriginDetection:
    """Testes para detecção de origem do lead baseada no canal."""

    def test_detect_whatsapp_origin(self):
        """WhatsApp deve ser detectado como lp_whatsapp (Inbox 4)."""
        origin = _detect_inbox_origin("WhatsApp")
        assert origin == "lp_whatsapp"

    def test_detect_site_widget_origin(self):
        """Site deve ser detectado como lp_widget (Inbox 5)."""
        origin = _detect_inbox_origin("Site")
        assert origin == "lp_widget"

    def test_detect_messenger_origin(self):
        """Messenger deve ser detectado como meta_dm (Inbox 3)."""
        origin = _detect_inbox_origin("Messenger")
        assert origin == "meta_dm"

    def test_detect_instagram_origin(self):
        """Instagram deve ser detectado como meta_dm (Inbox 3)."""
        origin = _detect_inbox_origin("Instagram")
        assert origin == "meta_dm"

    def test_detect_email_origin(self):
        """Email deve ser detectado como meta_dm (fallback)."""
        origin = _detect_inbox_origin("Email")
        assert origin == "meta_dm"

    def test_detect_telegram_origin(self):
        """Telegram deve ser detectado como meta_dm (fallback)."""
        origin = _detect_inbox_origin("Telegram")
        assert origin == "meta_dm"

    def test_detect_unknown_channel_origin(self):
        """Canal desconhecido deve usar fallback meta_dm."""
        origin = _detect_inbox_origin("UnknownChannel")
        assert origin == "meta_dm"


@pytest.mark.asyncio
class TestChannelInstructions:
    """Testes para injeção de instruções específicas por canal."""

    async def test_lp_whatsapp_instructions_injected(self):
        """Instruções LP WhatsApp devem ser injetadas para canal WhatsApp."""
        from unittest.mock import AsyncMock, patch

        # Mock dependencies
        with patch("app.guards.context_builder.get_agent_config", new=AsyncMock(return_value={})):
            with patch("app.guards.context_builder.get_company_info", new=AsyncMock(return_value={})):
                with patch("app.guards.context_builder.get_products", new=AsyncMock(return_value=[])):
                    with patch("app.guards.context_builder.get_qualification_steps", new=AsyncMock(return_value=[])):
                        with patch("app.guards.context_builder.get_hot_criteria", new=AsyncMock(return_value="")):
                            with patch("app.guards.context_builder.get_forbidden_topics", new=AsyncMock(return_value=[])):
                                with patch("app.guards.context_builder.get_valid_labels", new=AsyncMock(return_value=[])):
                                    with patch("app.guards.context_builder.search_knowledge", new=AsyncMock(return_value=[])):
                                        with patch("app.guards.context_builder.get_conversation_history", new=AsyncMock(return_value=[])):
                                            with patch("app.guards.context_builder._get_deal_stage_for_context", new=AsyncMock(return_value="")):

                                                from app.guards.context_builder import build_context

                                                # Test WhatsApp channel
                                                context = await build_context(
                                                    org_id="test-org",
                                                    agent_config={},
                                                    conversation_id="123",
                                                    contact_phone="+5511999999999",
                                                    contact_name="Test User",
                                                    channel="WhatsApp",
                                                    agent_type="sdr"
                                                )

                                                # Should contain LP WhatsApp instructions
                                                assert "ORIGEM: LP WHATSAPP" in context
                                                assert "já visitou nosso material da Lebedenco" in context
                                                assert "Pular apresentação institucional" in context

    async def test_site_widget_instructions_injected(self):
        """Instruções LP Widget devem ser injetadas para canal Site."""
        from unittest.mock import AsyncMock, patch

        # Mock all dependencies (same as above)
        with patch("app.guards.context_builder.get_agent_config", new=AsyncMock(return_value={})):
            with patch("app.guards.context_builder.get_company_info", new=AsyncMock(return_value={})):
                with patch("app.guards.context_builder.get_products", new=AsyncMock(return_value=[])):
                    with patch("app.guards.context_builder.get_qualification_steps", new=AsyncMock(return_value=[])):
                        with patch("app.guards.context_builder.get_hot_criteria", new=AsyncMock(return_value="")):
                            with patch("app.guards.context_builder.get_forbidden_topics", new=AsyncMock(return_value=[])):
                                with patch("app.guards.context_builder.get_valid_labels", new=AsyncMock(return_value=[])):
                                    with patch("app.guards.context_builder.search_knowledge", new=AsyncMock(return_value=[])):
                                        with patch("app.guards.context_builder.get_conversation_history", new=AsyncMock(return_value=[])):
                                            with patch("app.guards.context_builder._get_deal_stage_for_context", new=AsyncMock(return_value="")):

                                                from app.guards.context_builder import build_context

                                                # Test Site channel
                                                context = await build_context(
                                                    org_id="test-org",
                                                    agent_config={},
                                                    conversation_id="123",
                                                    contact_phone="+5511999999999",
                                                    contact_name="Test User",
                                                    channel="Site",
                                                    agent_type="sdr"
                                                )

                                                # Should contain LP Widget instructions
                                                assert "ORIGEM: LP WIDGET" in context
                                                assert "preencheu pre-chat form no nosso site" in context
                                                assert "CAPTURAR WhatsApp/email na 2ª mensagem" in context

    async def test_messenger_dm_instructions_injected(self):
        """Instruções Meta DM devem ser injetadas para canal Messenger."""
        from unittest.mock import AsyncMock, patch

        # Mock all dependencies (same as above)
        with patch("app.guards.context_builder.get_agent_config", new=AsyncMock(return_value={})):
            with patch("app.guards.context_builder.get_company_info", new=AsyncMock(return_value={})):
                with patch("app.guards.context_builder.get_products", new=AsyncMock(return_value=[])):
                    with patch("app.guards.context_builder.get_qualification_steps", new=AsyncMock(return_value=[])):
                        with patch("app.guards.context_builder.get_hot_criteria", new=AsyncMock(return_value="")):
                            with patch("app.guards.context_builder.get_forbidden_topics", new=AsyncMock(return_value=[])):
                                with patch("app.guards.context_builder.get_valid_labels", new=AsyncMock(return_value=[])):
                                    with patch("app.guards.context_builder.search_knowledge", new=AsyncMock(return_value=[])):
                                        with patch("app.guards.context_builder.get_conversation_history", new=AsyncMock(return_value=[])):
                                            with patch("app.guards.context_builder._get_deal_stage_for_context", new=AsyncMock(return_value="")):

                                                from app.guards.context_builder import build_context

                                                # Test Messenger channel
                                                context = await build_context(
                                                    org_id="test-org",
                                                    agent_config={},
                                                    conversation_id="123",
                                                    contact_phone="+5511999999999",
                                                    contact_name="Test User",
                                                    channel="Messenger",
                                                    agent_type="sdr"
                                                )

                                                # Should contain Meta DM instructions
                                                assert "ORIGEM: META DM" in context
                                                assert "PODE NÃO TER CONTEXTO da Lebedenco" in context
                                                assert "apresentar brevemente a empresa" in context

    def test_channel_instructions_for_non_whatsapp(self):
        """Canais não-WhatsApp devem ter instruções de captura específicas."""
        from app.guards.context_builder import _detect_inbox_origin

        # Test que cada canal não-WhatsApp tem diferenciação
        non_whatsapp_channels = ["Instagram", "Messenger", "Site", "Email", "Telegram"]

        for channel in non_whatsapp_channels:
            origin = _detect_inbox_origin(channel)
            # Todos devem ter origem definida (não None)
            assert origin in ["lp_widget", "meta_dm"], f"Channel {channel} should have valid origin"