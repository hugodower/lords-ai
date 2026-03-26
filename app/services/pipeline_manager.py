"""Pipeline manager — auto-move deals through CRM stages based on Aurora's actions.

Creates contacts and deals automatically when they don't exist yet.
"""
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
    "agendado": [r"agendad", r"agenda", r"scheduled", r"meeting", r"reuni"],
    "negociacao": [r"negocia", r"negotiat"],
    "perdido": [r"perdid", r"lost", r"perda"],
    "ganho": [r"ganh", r"won", r"fechad", r"converted"],
}

# Position-based fallback (0-indexed)
POSITION_FALLBACK = {
    "qualificado": 1,
    "oportunidade": 2,
    "agendado": 3,
    "negociacao": 4,
}

# Label → stage mapping
LABEL_TO_STAGE = {
    "novo_lead": "primeiro_contato",
    "novo-lead": "primeiro_contato",
    "qualificado": "qualificado",
    "lead_quente": "oportunidade",
    "lead-quente": "oportunidade",
    "reuniao_agendada": "agendado",
    "reuniao-agendada": "agendado",
    "em_negociacao": "negociacao",
    "em-negociacao": "negociacao",
    "fechou": "ganho",
    "perdido": "perdido",
}


def _find_stage(stages: list[dict], target: str) -> Optional[dict]:
    """Find a stage by name pattern match, falling back to position.

    Args:
        stages: Pipeline stages ordered by position.
        target: Stage key (primeiro_contato, qualificado, oportunidade,
                agendado, negociacao, perdido, ganho).
    """
    if not stages:
        return None

    # First stage shortcut
    if target == "primeiro_contato":
        return stages[0]

    # Last stage shortcut for perdido
    if target == "perdido":
        for stage in stages:
            name = (stage.get("name") or "").lower()
            for pattern in STAGE_PATTERNS.get("perdido", []):
                if re.search(pattern, name, re.IGNORECASE):
                    return stage
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


async def ensure_deal_exists(
    org_id: str,
    contact_phone: str,
    contact_name: str = "",
) -> Optional[dict]:
    """Find or create contact + deal. Returns the deal dict or None.

    1. Find contact by phone (multiple formats)
    2. If not found, create contact
    3. Find deal for that contact
    4. If not found, create deal in first stage of default pipeline
    """
    # ── Step 1: Find or create contact ─────────────────────────────
    contact = await sb.find_contact_by_phone(org_id, contact_phone)

    if not contact:
        contact = await sb.create_contact(
            org_id=org_id,
            name=contact_name or "Sem nome",
            phone=contact_phone,
            source="whatsapp",
        )
        if not contact:
            log.error(
                "[PIPELINE] Could not create contact for phone=%s org=%s",
                contact_phone, org_id,
            )
            return None

    contact_id = contact["id"]

    # ── Step 2: Find existing deal ─────────────────────────────────
    supabase = sb.get_supabase()
    try:
        deal_resp = (
            supabase.table("deals")
            .select("id, stage_id, pipeline_id, status, value")
            .eq("organization_id", org_id)
            .eq("contact_id", contact_id)
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
        if deal_resp and deal_resp.data:
            return deal_resp.data[0]
    except Exception as exc:
        log.error("[PIPELINE] Error querying deals for contact=%s: %s", contact_id, exc)

    # ── Step 3: Create deal in first stage ─────────────────────────
    stages = await sb.get_pipeline_stages(org_id)
    if not stages:
        log.warning(
            "[PIPELINE] No pipeline/stages for org=%s — cannot create deal",
            org_id,
        )
        return None

    first_stage = stages[0]
    pipeline_id = first_stage["pipeline_id"]
    stage_id = first_stage["id"]
    stage_name = first_stage.get("name", "?")

    deal = await sb.create_deal(
        org_id=org_id,
        contact_id=contact_id,
        pipeline_id=pipeline_id,
        stage_id=stage_id,
    )

    if deal:
        display_name = contact_name or contact.get("name", contact_phone)
        log.info(
            "[PIPELINE:CREATE] Deal criado para %s (%s) na etapa '%s'",
            display_name, contact_phone, stage_name,
        )

    return deal


async def move_deal_to_stage(
    org_id: str,
    contact_phone: str,
    target_stage: str,
    contact_name: str = "",
) -> bool:
    """Move a deal to the target pipeline stage, creating contact+deal if needed.

    Args:
        org_id: Organization ID.
        contact_phone: Contact's phone number.
        target_stage: Stage key (primeiro_contato, qualificado, oportunidade,
                      agendado, negociacao, perdido, ganho).
        contact_name: Contact name (used when creating new contact/deal).

    Returns True if deal was moved (or created) successfully.
    """
    try:
        # Ensure deal exists (creates contact + deal if needed)
        deal = await ensure_deal_exists(org_id, contact_phone, contact_name)
        if not deal:
            log.warning(
                "[PIPELINE] Could not find/create deal for phone=%s org=%s",
                contact_phone, org_id,
            )
            return False

        deal_id = deal["id"]
        pipeline_id = deal.get("pipeline_id")
        current_stage_id = deal.get("stage_id")

        stages = await sb.get_pipeline_stages(org_id, pipeline_id)
        if not stages:
            log.warning(
                "[PIPELINE] No stages for pipeline=%s org=%s",
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
                "[PIPELINE] Deal %s already in '%s' — skipping",
                deal_id, target.get("name"),
            )
            return True

        # Find current stage name for the log
        current_name = "?"
        for s in stages:
            if s["id"] == current_stage_id:
                current_name = s.get("name", "?")
                break

        success = await sb.update_deal_stage(deal_id, target_stage_id)
        if success:
            log.info(
                "[PIPELINE:MOVE] Deal %s movido de '%s' para '%s' — phone=%s",
                deal_id, current_name, target.get("name"), contact_phone,
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
