from __future__ import annotations

from typing import Optional

import httpx

from app.config import settings
from app.utils.logger import get_logger

log = get_logger("chatwoot")

DEFAULT_AI_AGENT_EMAIL = "aurora@ai.lordsads.uk"


class ChatwootClient:
    def __init__(self) -> None:
        self.base_url = settings.chatwoot_url.rstrip("/")
        self.account_id = settings.chatwoot_account_id
        self.headers = {
            "api_access_token": settings.chatwoot_api_token,
            "Content-Type": "application/json",
        }
        # Cache: {account_id: ai_agent_id or None}
        self._ai_agent_cache: dict[str, int | None] = {}

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

    # ── AI Agent auto-assign ─────────────────────────────────────────────

    async def _get_ai_agent_email(self, org_id: str = "") -> str:
        """Get the AI agent email for an org, fallback to default."""
        if not org_id:
            return DEFAULT_AI_AGENT_EMAIL
        try:
            from app.integrations import supabase_client as sb
            active = await sb.get_active_agents(org_id)
            if active:
                email = active[0].get("chatwoot_agent_email")
                if email:
                    return email
        except Exception as exc:
            log.warning("[AI_AGENT] Failed to get agent email for org %s: %s", org_id, exc)
        return DEFAULT_AI_AGENT_EMAIL

    async def _get_ai_agent_id(
        self, base_url: str, account_id: int, headers: dict,
        agent_email: str = "",
    ) -> int | None:
        """Get AI agent's Chatwoot agent_id, cached per account."""
        if not agent_email:
            agent_email = DEFAULT_AI_AGENT_EMAIL
        cache_key = f"{account_id}:{agent_email}"
        if cache_key in self._ai_agent_cache:
            return self._ai_agent_cache[cache_key]

        url = f"{base_url}/api/v1/accounts/{account_id}/agents"
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(url, headers=headers)
                resp.raise_for_status()
                for agent in resp.json():
                    if agent.get("email") == agent_email:
                        aid = agent["id"]
                        self._ai_agent_cache[cache_key] = aid
                        log.info(
                            "[AI_AGENT] Cached agent_id=%d for account %s (email=%s)",
                            aid, account_id, agent_email,
                        )
                        return aid
            self._ai_agent_cache[cache_key] = None
            log.warning("[AI_AGENT] Agent %s not found in account %s", agent_email, account_id)
            return None
        except Exception as e:
            log.warning("[AI_AGENT] Failed to fetch agents for account %s: %s", account_id, e)
            return None

    async def _auto_assign_ai_agent(
        self,
        conversation_id: str,
        base_url: str,
        account_id: int,
        headers: dict,
        org_id: str = "",
    ) -> None:
        """Assign AI agent to conversation if no agent is assigned yet."""
        agent_email = await self._get_ai_agent_email(org_id)
        ai_agent_id = await self._get_ai_agent_id(base_url, account_id, headers, agent_email=agent_email)
        if not ai_agent_id:
            return

        conv_url = f"{base_url}/api/v1/accounts/{account_id}/conversations/{conversation_id}"
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(conv_url, headers=headers)
                resp.raise_for_status()
                conv = resp.json()

                assignee = conv.get("meta", {}).get("assignee") or conv.get("assignee")
                if assignee:
                    return  # Human agent already assigned, don't overwrite

                assign_url = f"{conv_url}/assignments"
                resp = await client.post(
                    assign_url, json={"assignee_id": ai_agent_id}, headers=headers
                )
                resp.raise_for_status()
                log.info("[AI_AGENT] Auto-assigned to conv %s", conversation_id)
        except Exception as e:
            log.warning("[AI_AGENT] Auto-assign failed for conv %s: %s", conversation_id, e)

    # ── Message sending ─────────────────────────────────────────────────

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
                result = resp.json()
        except Exception as e:
            log.error(
                "Failed to send message to conv %s (base_url=%s, account=%s): %s",
                conversation_id, base_url, account_id, e,
            )
            return {"error": str(e)}

        # Auto-assign AI agent for non-private outgoing messages
        if not private:
            try:
                await self._auto_assign_ai_agent(
                    conversation_id, base_url, account_id, headers, org_id=org_id
                )
            except Exception as assign_err:
                log.warning("[AI_AGENT] Auto-assign error: %s", assign_err)

        return result

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

    async def update_contact(
        self,
        contact_id: int,
        name: str = "",
        phone_number: str = "",
        email: str = "",
        custom_attributes: Optional[dict] = None,
    ) -> Optional[dict]:
        """Update an existing Chatwoot contact with real data.

        Used to fix contacts that came as 'John Doe' from Meta Lead Ads,
        replacing placeholder data with the real lead information parsed
        from message content.

        Args:
            contact_id: Chatwoot contact ID to update
            name: Real full name (skips if empty)
            phone_number: Phone number with country code (skips if empty)
            email: Email address (skips if empty)
            custom_attributes: Dict of custom attributes to merge

        Returns:
            Updated contact dict on success, None on 404 or empty payload
        """
        url = self._url(f"/contacts/{contact_id}")

        payload: dict = {}
        if name:
            payload["name"] = name
        if phone_number:
            payload["phone_number"] = phone_number
        if email:
            payload["email"] = email
        if custom_attributes:
            payload["custom_attributes"] = custom_attributes

        if not payload:
            log.info(
                "[CHATWOOT:UPDATE_CONTACT] No data to update for contact %s",
                contact_id,
            )
            return None

        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.patch(
                    url,
                    headers=self.headers,
                    json=payload,
                )
                if resp.status_code == 404:
                    log.warning(
                        "[CHATWOOT:UPDATE_CONTACT] Contact %s not found (404)",
                        contact_id,
                    )
                    return None
                resp.raise_for_status()
                log.info(
                    "[CHATWOOT:UPDATE_CONTACT] Contact %s updated: name='%s' phone='%s'",
                    contact_id, name, phone_number,
                )
                return resp.json()
        except Exception as exc:
            log.error(
                "[CHATWOOT:UPDATE_CONTACT:ERROR] Contact %s — %s",
                contact_id, exc,
            )
            return None


chatwoot_client = ChatwootClient()
