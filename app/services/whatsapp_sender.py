"""Send WhatsApp template messages via Meta Cloud API."""
from __future__ import annotations

from typing import Optional

import httpx

from app.utils.logger import get_logger

log = get_logger("followup:whatsapp")

META_API_URL = "https://graph.facebook.com/v21.0"


async def send_template(
    phone_number_id: str,
    access_token: str,
    to_phone: str,
    template_name: str,
    variables: list[str],
    language: str = "pt_BR",
) -> dict:
    """Send a WhatsApp template message via Meta Cloud API.

    Returns dict with ``success`` bool and either ``wamid`` or ``error``.
    """
    url = f"{META_API_URL}/{phone_number_id}/messages"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }

    # Build template components
    components = []
    if variables:
        components.append({
            "type": "body",
            "parameters": [
                {"type": "text", "text": v} for v in variables
            ],
        })

    payload = {
        "messaging_product": "whatsapp",
        "to": to_phone.replace("+", "").replace(" ", "").replace("-", ""),
        "type": "template",
        "template": {
            "name": template_name,
            "language": {"code": language},
            "components": components,
        },
    }

    log.info(
        "[FOLLOWUP:WHATSAPP] Sending template '%s' to %s via phone_number_id=%s",
        template_name, to_phone, phone_number_id,
    )

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(url, json=payload, headers=headers)

        if resp.status_code == 200:
            data = resp.json()
            wamid = (data.get("messages") or [{}])[0].get("id", "")
            log.info(
                "[FOLLOWUP:WHATSAPP] SUCCESS — template=%s to=%s wamid=%s",
                template_name, to_phone, wamid,
            )
            return {"success": True, "wamid": wamid}

        error_body = resp.text[:500]
        log.error(
            "[FOLLOWUP:WHATSAPP] FAIL — status=%d template=%s to=%s error=%s",
            resp.status_code, template_name, to_phone, error_body,
        )
        return {"success": False, "error": f"HTTP {resp.status_code}: {error_body}"}

    except Exception as exc:
        log.error(
            "[FOLLOWUP:WHATSAPP] EXCEPTION — template=%s to=%s: %s",
            template_name, to_phone, exc,
        )
        return {"success": False, "error": str(exc)}
