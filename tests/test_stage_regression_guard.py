"""
Testes do guard de retrocesso de stage (Bloco 3 / Risco 1).
"""
import pytest
from unittest.mock import AsyncMock, patch

from app.services.pipeline_manager import (
    get_current_stage,
    update_stage,
)


@pytest.mark.asyncio
async def test_get_current_stage_sem_contato():
    """Sem contato → retorna None, não levanta exceção."""
    with patch("app.services.pipeline_manager.sb.find_contact_by_phone", new=AsyncMock(return_value=None)):
        result = await get_current_stage("org_test", "+5500000000000")
        assert result is None


@pytest.mark.asyncio
async def test_get_current_stage_sem_deal():
    """Com contato mas sem deal → retorna None."""
    with patch("app.services.pipeline_manager.sb.find_contact_by_phone", new=AsyncMock(return_value={"id": "c1"})), \
         patch("app.services.pipeline_manager.sb.find_deal_for_contact", new=AsyncMock(return_value=None)):
        result = await get_current_stage("org_test", "+5500000000000")
        assert result is None


@pytest.mark.asyncio
async def test_update_stage_recusa_retrocesso():
    """
    Deal em '03. Reunião Agendada' (position 3) e Aurora tenta voltar para '02-qualificacao' (position 2).
    Deve retornar False e logar warning.
    """
    with patch("app.services.pipeline_manager.get_current_stage",
               new=AsyncMock(return_value={"name": "03. Reunião Agendada", "position": 3})), \
         patch("app.services.pipeline_manager._get_stage_position_by_chatwoot_label",
               new=lambda org_id, label: 2):  # retorna position 2 para "02-qualificacao"
        result = await update_stage("org_test", "+5500000000000", "conv123", "02-qualificacao")
        assert result is False