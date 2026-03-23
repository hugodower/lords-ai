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

    async def send_message(
        self, conversation_id: str, text: str, private: bool = False
    ) -> dict:
        url = self._url(f"/conversations/{conversation_id}/messages")
        payload = {
            "content": text,
            "message_type": "outgoing",
            "private": private,
        }
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(url, json=payload, headers=self.headers)
                resp.raise_for_status()
                log.info(
                    "Message sent to conversation %s (private=%s)", conversation_id, private
                )
                return resp.json()
        except Exception as e:
            log.error("Failed to send message to conversation %s: %s", conversation_id, e)
            return {"error": str(e)}

    async def send_private_note(self, conversation_id: str, note_text: str) -> dict:
        return await self.send_message(conversation_id, note_text, private=True)

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

    async def add_label(self, conversation_id: str, label: str) -> dict:
        url = self._url(f"/conversations/{conversation_id}/labels")
        async with httpx.AsyncClient(timeout=10) as client:
            # Get existing labels first
            resp = await client.get(url, headers=self.headers)
            resp.raise_for_status()
            existing = resp.json().get("payload", [])
            labels = list(set(existing + [label]))
            resp = await client.post(url, json={"labels": labels}, headers=self.headers)
            resp.raise_for_status()
            log.info("Added label '%s' to conversation %s", label, conversation_id)
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
