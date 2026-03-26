"""Pipeline manager — auto-move deals through CRM stages based on Aurora's actions."""
from __future__ import annotations

import re
from typing import Optional

import httpx

from app.config import settings
from app.integrations import supabase_client as sb
from app.utils.logger import get_logger

log = get_logger("pipeline")

# Stage name patterns for matching (case-insensitive)
STAGE_PATTERNS = {
    "qualificado": [r"qualificad", r"qualified"],
    "oportunidade": [r"oportunidad", r"opportunity"],
    "agendado": [r"agendad", r"agenda", r"scheduled", r"meeting"],
    "negociacao": [r"negocia", r"negotiat"],
    "perdido": [r"perdid", r"lost", r"perda"],
}

# Position-based fallback (0-indexed)
POSITION_FALLBACK = {
    "qualificado": 1,
    "oportunidade": 2,
    "agendado": 3,
    "negociacao": 4,
}


def _find_stage(stages: list[dict], target: str) -> Optional[dict]:
    """Find a stage by name pattern match, falling back to position.

    Args:
        stages: Pipeline stages ordered by position.
        target: Stage key (primeiro_contato, qualificado, oportunidade, agendado, negociacao, perdido).
    """
    if not stages:
        return None

    # First stage shortcut
    if target == "primeiro_contato":
        return stages[0]

    # Last stage shortcut
    if target == "perdido":
        # Try name match first
        for stage in stages:
            name = (stage.get("name") or "").lower()
            for pattern in STAGE_PATTERNS.get("perdido", []):
                if re.search(pattern, name, re.IGNORECASE):
                    return stage
        # Fallback: last stage
        return stages[-1]

    # Name match
    patterns = STAGE_PATTERNS.get(target, [])
    for stage in stages:
        name = (stage.get("name") or "").lower()
        for pattern in patterns:
            if re.search(pattern, name, re.IGNORECASE):
                return stage

    # Position fallback
    pos = POSITION_FALLBACK.get(target)
    if pos is not None and pos < len(stages):
        return stages[pos]

    return None


async def move_deal_to_stage(
    org_id: str,
    contact_phone: str,
    target_stage: str,
) -> bool:
    """Move a deal to the target pipeline stage.

    Args:
        org_id: Organization ID.
        contact_phone: Contact's phone number.
        target_stage: Stage key (primeiro_contato, qualificado, oportunidade,
                      agendado, negociacao, perdido).

    Returns True if deal was moved successfully.
    """
    try:
        deal = await sb.get_deal_by_contact_phone(org_id, contact_phone)
        if not deal:
            log.info(
                "[PIPELINE] No deal found for phone=%s org=%s — skipping move to '%s'",
                contact_phone, org_id, target_stage,
            )
            return False

        deal_id = deal["id"]
        pipeline_id = deal.get("pipeline_id")
        current_stage_id = deal.get("stage_id")

        stages = await sb.get_pipeline_stages(org_id, pipeline_id)
        if not stages:
            log.warning(
                "[PIPELINE] No stages found for pipeline=%s org=%s",
                pipeline_id, org_id,
            )
            return False

        target = _find_stage(stages, target_stage)
        if not target:
            log.warning(
                "[PIPELINE] Stage '%s' not found in pipeline=%s (available: %s)",
                target_stage, pipeline_id,
                [s.get("name") for s in stages],
            )
            return False

        target_stage_id = target["id"]

        if current_stage_id == target_stage_id:
            log.info(
                "[PIPELINE] Deal %s already in stage '%s' — skipping",
                deal_id, target.get("name"),
            )
            return True

        success = await sb.update_deal_stage(deal_id, target_stage_id)
        if success:
            log.info(
                "[PIPELINE] Deal %s moved to '%s' (id=%s) — phone=%s",
                deal_id, target.get("name"), target_stage_id, contact_phone,
            )
            if target_stage == "perdido":
                await sb.update_deal_lost(deal_id)

        return success

    except Exception as exc:
        log.error(
            "[PIPELINE] Error moving deal to '%s' for phone=%s: %s",
            target_stage, contact_phone, exc,
        )
        return False


async def add_label_to_chatwoot(
    org_id: str,
    conversation_id: str,
    label: str,
) -> bool:
    """Add a label to a Chatwoot conversation using per-org credentials.

    Falls back to global settings if per-org credentials are unavailable.
    """
    try:
        conn = await sb.get_chatwoot_connection(org_id)

        base_url = settings.chatwoot_url.rstrip("/")
        account_id = settings.chatwoot_account_id
        token = settings.chatwoot_api_token

        if conn:
            base_url = (
                conn.get("base_url")
                or conn.get("chatwoot_base_url")
                or base_url
            ).rstrip("/")
            account_id = conn.get("chatwoot_account_id") or account_id
            token = (
                conn.get("api_access_token")
                or conn.get("chatwoot_api_token")
                or token
            )

        headers = {"api_access_token": token, "Content-Type": "application/json"}
        url = f"{base_url}/api/v1/accounts/{account_id}/conversations/{conversation_id}/labels"

        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(url, headers=headers)
            resp.raise_for_status()
            existing = resp.json().get("payload", [])
            labels = list(set(existing + [label]))

            resp = await client.post(url, json={"labels": labels}, headers=headers)
            resp.raise_for_status()

        log.info(
            "[PIPELINE] Label '%s' added to conversation %s",
            label, conversation_id,
        )
        return True

    except Exception as exc:
        log.error(
            "[PIPELINE] Failed to add label '%s' to conv %s: %s",
            label, conversation_id, exc,
        )
        return False
