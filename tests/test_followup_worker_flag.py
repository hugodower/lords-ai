"""Testes para a feature flag do followup worker."""
import asyncio
from unittest.mock import patch, MagicMock

import pytest

from app.services.followup_worker import start_worker


@pytest.mark.asyncio
class TestFollowupWorkerFlag:
    """Testes para FOLLOWUP_WORKER_ENABLED feature flag."""

    async def test_worker_disabled_via_flag(self):
        """Worker deve ficar em loop idle quando FOLLOWUP_WORKER_ENABLED=False."""
        with patch("app.services.followup_worker.settings") as mock_settings:
            mock_settings.followup_worker_enabled = False

            # Mock da função _process_pending para verificar que não é chamada
            with patch("app.services.followup_worker._process_pending") as mock_process:
                # Mock do sleep para não aguardar 60s
                with patch("app.services.followup_worker.asyncio.sleep") as mock_sleep:
                    # Simular shutdown após 2 iterações
                    sleep_count = 0

                    async def mock_sleep_func(seconds):
                        nonlocal sleep_count
                        sleep_count += 1
                        if sleep_count >= 2:
                            # Trigger shutdown após 2 iterações
                            import app.services.followup_worker as fw
                            fw._shutdown = True

                    mock_sleep.side_effect = mock_sleep_func

                    # Executar worker
                    await start_worker()

                    # Verificações
                    assert mock_process.call_count == 0, "_process_pending não deve ser chamada quando disabled"
                    assert mock_sleep.call_count == 2, "Deve fazer sleep 2 vezes (loop idle)"
                    mock_sleep.assert_called_with(60)  # POLL_INTERVAL_SECONDS

    async def test_worker_enabled_processes_normally(self):
        """Worker deve processar normalmente quando FOLLOWUP_WORKER_ENABLED=True."""
        with patch("app.services.followup_worker.settings") as mock_settings:
            mock_settings.followup_worker_enabled = True

            # Mock da função _process_pending
            with patch("app.services.followup_worker._process_pending") as mock_process:
                # Mock do sleep para não aguardar 60s
                with patch("app.services.followup_worker.asyncio.sleep") as mock_sleep:
                    # Simular shutdown após 2 iterações
                    process_count = 0

                    async def mock_process_func():
                        nonlocal process_count
                        process_count += 1
                        if process_count >= 2:
                            # Trigger shutdown após 2 iterações
                            import app.services.followup_worker as fw
                            fw._shutdown = True

                    mock_process.side_effect = mock_process_func

                    # Mock sleep para não aguardar
                    mock_sleep.side_effect = lambda seconds: None

                    # Executar worker
                    await start_worker()

                    # Verificações
                    assert mock_process.call_count == 2, "_process_pending deve ser chamada quando enabled"
                    assert mock_sleep.call_count == 2, "Deve fazer sleep após cada processamento"

    async def test_worker_logs_warning_when_disabled(self, caplog):
        """Worker deve logar warning quando desabilitado."""
        with patch("app.services.followup_worker.settings") as mock_settings:
            mock_settings.followup_worker_enabled = False

            with patch("app.services.followup_worker.asyncio.sleep") as mock_sleep:
                # Simular shutdown imediato
                async def mock_sleep_func(seconds):
                    import app.services.followup_worker as fw
                    fw._shutdown = True

                mock_sleep.side_effect = mock_sleep_func

                # Executar worker
                await start_worker()

                # Verificar log warning
                assert "Worker disabled via FOLLOWUP_WORKER_ENABLED flag" in caplog.text

    async def test_worker_default_enabled_true(self):
        """Por padrão, worker deve estar enabled (FOLLOWUP_WORKER_ENABLED=True)."""
        from app.config import Settings

        # Criar settings sem override
        settings = Settings(
            org_id="test-org",
            supabase_url="http://test.supabase.co",
            supabase_service_key="test-key",
            claude_api_key="test-claude-key",
            chatwoot_url="http://test.chatwoot.url",
            chatwoot_api_token="test-token"
        )

        # Default deve ser True
        assert settings.followup_worker_enabled is True