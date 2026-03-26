from __future__ import annotations

from typing import Optional

import httpx

from app.config import settings
from app.utils.logger import get_logger

log = get_logger("chatwoot")


class ChatwootClient:
    def __init__(self) -> None:
        self.base_url = settings.chatwoot_url.rstrip("/")
        self.account_id = settings.chatwoot_account_id
        self.headers = {
            "api_access_token": settings.chatwoot_api_token,
            "Content-Type": "application/json",
        }

    def _url(self, path: str) -> str:
        return f"{self.base_url}/api/v1/accounts/{self.account_id}{path}"

    def _resolve_config(self, conn: dict | None) -> tuple[str, int, dict]:
        """Return (base_url, account_id, headers) from per-org connection or global."""
        if not conn:
            return self.base_url, self.account_id, self.headers

        base_url = (
            conn.get("base_url") or conn.get("chatwoot_base_url") or self.base_url
        ).rstrip("/")
        account_id = conn.get("chatwoot_account_id") or self.account_id
        token = (
            conn.get("api_access_token") or conn.get("chatwoot_api_token")
            or settings.chatwoot_api_token
        )
        headers = {"api_access_token": token, "Content-Type": "application/json"}
        return base_url, account_id, headers

    async def send_message(
        self,
        conversation_id: str,
        text: str,
        private: bool = False,
        org_id: str = "",
    ) -> dict:
        """Send message using per-org credentials if available, fallback to global."""
        conn = None
        if org_id:
            try:
                from app.integrations import supabase_client as sb
                conn = await sb.get_chatwoot_connection_cached(org_id)
            except Exception as exc:
                log.warning("[CHATWOOT] Failed to get per-org connection: %s", exc)

        base_url, account_id, headers = self._resolve_config(conn)
        url = f"{base_url}/api/v1/accounts/{account_id}/conversations/{conversation_id}/messages"
        payload = {
            "content": text,
            "message_type": "outgoing",
            "private": private,
        }
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(url, json=payload, headers=headers)
                resp.raise_for_status()
                log.info(
                    "Message sent to conv %s (private=%s, org=%s)",
                    conversation_id, private, org_id or "global",
                )
                return resp.json()
        except Exception as e:
            log.error(
                "Failed to send message to conv %s (base_url=%s, account=%s): %s",
                conversation_id, base_url, account_id, e,
            )
            return {"error": str(e)}

    async def send_private_note(
        self, conversation_id: str, note_text: str, org_id: str = ""
    ) -> dict:
        return await self.send_message(conversation_id, note_text, private=True, org_id=org_id)

    async def assign_agent(self, conversation_id: str, agent_id: int) -> dict:
        url = self._url(f"/conversations/{conversation_id}/assignments")
        payload = {"assignee_id": agent_id}
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(url, json=payload, headers=self.headers)
            resp.raise_for_status()
            log.info(
                "Assigned agent %s to conversation %s", agent_id, conversation_id
            )
            return resp.json()

    async def get_contact_info(self, contact_id: int) -> Optional[dict]:
        url = self._url(f"/contacts/{contact_id}")
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(url, headers=self.headers)
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            return resp.json()


chatwoot_client = ChatwootClient()
