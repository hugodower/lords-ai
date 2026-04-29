"""
Tests for app.integrations.supabase_client module.

Currently covers: get_org_by_chatwoot_account (VPS-scoped lookup).
"""
from unittest.mock import patch, MagicMock
from types import SimpleNamespace

import pytest

from app.integrations.supabase_client import get_org_by_chatwoot_account


@pytest.mark.asyncio
class TestGetOrgByChatwootAccount:
    """
    Tests for VPS-scoped Chatwoot account → org lookup.

    Context: each org runs in its own dedicated VPS but shares a central
    Supabase. The lookup must be filtered by settings.org_id to prevent
    ambiguity when chatwoot_account_id collides across orgs.
    """

    def _build_mock_chain(self, response_data):
        """
        Build a chainable mock that mimics:
            sb.table().select().eq().eq().maybe_single().execute()

        Returns the mock chain. Each .eq() is chainable to itself.
        """
        chain = MagicMock()
        chain.table.return_value = chain
        chain.select.return_value = chain
        chain.eq.return_value = chain
        chain.maybe_single.return_value = chain
        chain.execute.return_value = SimpleNamespace(data=response_data)
        return chain

    async def test_returns_org_id_when_match_found(self):
        """Happy path: account_id matches in current VPS scope -> returns org_id."""
        expected_org = "cc000000-0000-0000-0000-000000000001"
        mock_chain = self._build_mock_chain({"organization_id": expected_org})

        with patch("app.integrations.supabase_client.get_supabase", return_value=mock_chain):
            result = await get_org_by_chatwoot_account(1)

        assert result == expected_org

    async def test_returns_none_when_no_match(self):
        """No row matches in this VPS scope -> returns None."""
        mock_chain = self._build_mock_chain(None)

        with patch("app.integrations.supabase_client.get_supabase", return_value=mock_chain):
            result = await get_org_by_chatwoot_account(999)

        assert result is None

    async def test_returns_none_on_exception(self):
        """Supabase raises -> function returns None gracefully (does not propagate)."""
        mock_chain = MagicMock()
        mock_chain.table.return_value = mock_chain
        mock_chain.select.return_value = mock_chain
        mock_chain.eq.return_value = mock_chain
        mock_chain.maybe_single.return_value = mock_chain
        mock_chain.execute.side_effect = Exception("Supabase down")

        with patch("app.integrations.supabase_client.get_supabase", return_value=mock_chain):
            result = await get_org_by_chatwoot_account(1)

        assert result is None

    async def test_filter_by_chatwoot_account_id(self):
        """Confirms .eq('chatwoot_account_id', account_id) is called."""
        expected_org = "cc000000-0000-0000-0000-000000000001"
        mock_chain = self._build_mock_chain({"organization_id": expected_org})

        with patch("app.integrations.supabase_client.get_supabase", return_value=mock_chain):
            await get_org_by_chatwoot_account(42)

        # Confirm .eq was called with chatwoot_account_id=42
        eq_calls = mock_chain.eq.call_args_list
        eq_args = [call.args for call in eq_calls]
        assert ("chatwoot_account_id", 42) in eq_args

    async def test_filter_by_settings_org_id(self):
        """
        CRITICAL: Confirms .eq('organization_id', settings.org_id) is called.

        This is the VPS-scope filter that prevents cross-tenant lookups
        when multiple orgs share the same chatwoot_account_id.
        """
        expected_org = "cc000000-0000-0000-0000-000000000001"
        mock_chain = self._build_mock_chain({"organization_id": expected_org})

        with patch("app.integrations.supabase_client.get_supabase", return_value=mock_chain):
            with patch(
                "app.integrations.supabase_client.settings",
                MagicMock(org_id="test-org-001"),
            ):
                await get_org_by_chatwoot_account(1)

        # Confirm .eq was called with organization_id=test-org-001
        eq_calls = mock_chain.eq.call_args_list
        eq_args = [call.args for call in eq_calls]
        assert ("organization_id", "test-org-001") in eq_args