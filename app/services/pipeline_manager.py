"""Pipeline manager — auto-move deals through CRM stages based on Aurora's actions.

Creates contacts and deals automatically when they don't exist yet.
Swaps Chatwoot stage labels (mutually exclusive) on each transition.
"""
from __future__ import annotations

import re
from typing import Optional

import httpx

from app.config import settings
from app.integrations import supabase_client as sb
from app.utils.logger import get_logger

log = get_logger("pipeline")

# ── Stage name patterns for matching pipeline stages (case-insensitive) ──
STAGE_PATTERNS = {
    "primeiro_contato": [r"prospec", r"novo", r"new", r"primeiro"],
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

# ── Mutually exclusive stage labels in Chatwoot ──────────────────────────
STAGE_LABELS = {
    "novo_lead", "qualificado", "lead_quente",
    "reuniao_agendada", "em_negociacao", "fechou", "perdido",
}

# Label (Chatwoot) → stage key (pipeline)
LABEL_TO_STAGE = {
    "novo_lead": "primeiro_contato",
    "qualificado": "qualificado",
    "lead_quente": "oportunidade",
    "reuniao_agendada": "agendado",
    "em_negociacao": "negociacao",
    "fechou": "ganho",
    "perdido": "perdido",
}

# Stage key (pipeline) → label (Chatwoot)
STAGE_TO_LABEL = {
    "primeiro_contato": "novo_lead",
    "qualificado": "qualificado",
    "oportunidade": "lead_quente",
    "agendado": "reuniao_agendada",
    "negociacao": "em_negociacao",
    "ganho": "fechou",
    "perdido": "perdido",
}


# ── Chatwoot config helper ───────────────────────────────────────────────

def _resolve_chatwoot_config(conn: dict | None) -> tuple[str, int, str]:
    """Return (base_url, account_id, token) from connection or global settings."""
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

    return base_url, account_id, token


# ── Stage name matching ──────────────────────────────────────────────────

def _find_stage(stages: list[dict], target: str) -> Optional[dict]:
    """Find a pipeline stage by name pattern, falling back to position."""
    if not stages:
        return None

    # First stage shortcut
    if target == "primeiro_contato":
        # Try name match first
        for stage in stages:
            name = (stage.get("name") or "").lower()
            for pattern in STAGE_PATTERNS.get("primeiro_contato", []):
                if re.search(pattern, name, re.IGNORECASE):
                    return stage
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


# ── Contact + Deal creation ──────────────────────────────────────────────

async def ensure_deal_exists(
    org_id: str,
    contact_phone: str,
    contact_name: str = "",
) -> Optional[dict]:
    """Find or create contact + deal. Returns the deal dict or None."""
    # ── Find or create contact ──
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

    # ── Find existing deal ──
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
            log.info(
                "[PIPELINE:ENSURE] Deal ja existe para %s (deal_id=%s)",
                contact_phone, deal_resp.data[0]["id"],
            )
            return deal_resp.data[0]
    except Exception as exc:
        log.error("[PIPELINE] Error querying deals for contact=%s: %s", contact_id, exc)

    # ── Create deal in first stage ──
    stages = await sb.get_pipeline_stages(org_id)
    if not stages:
        log.warning("[PIPELINE] No pipeline/stages for org=%s — cannot create deal", org_id)
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
            "[PIPELINE:ENSURE] Criando deal para %s (%s) na etapa '%s'",
            display_name, contact_phone, stage_name,
        )

    return deal


# ── Deal stage movement ──────────────────────────────────────────────────

async def move_deal_to_stage(
    org_id: str,
    contact_phone: str,
    stage_key: str,
    contact_name: str = "",
) -> bool:
    """Move a deal to the target pipeline stage, creating contact+deal if needed."""
    try:
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
            log.warning("[PIPELINE] No stages for pipeline=%s org=%s", pipeline_id, org_id)
            return False

        target = _find_stage(stages, stage_key)
        if not target:
            log.warning(
                "[PIPELINE] Stage '%s' not found in pipeline=%s (available: %s)",
                stage_key, pipeline_id, [s.get("name") for s in stages],
            )
            return False

        target_stage_id = target["id"]

        if current_stage_id == target_stage_id:
            log.info("[PIPELINE] Deal %s already in '%s'", deal_id, target.get("name"))
            return True

        # Log current stage name
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
            if stage_key == "perdido":
                await sb.update_deal_lost(deal_id)

        return success

    except Exception as exc:
        log.error(
            "[PIPELINE] Error moving deal to '%s' for phone=%s: %s",
            stage_key, contact_phone, exc,
        )
        return False


# ── Chatwoot label management ────────────────────────────────────────────

async def _swap_chatwoot_label(
    org_id: str,
    conversation_id: str,
    new_label: str,
) -> bool:
    """Replace stage labels with new_label (removes old stage labels first).

    Uses GET conversation + PATCH conversation (not the /labels endpoint).
    """
    try:
        conn = await sb.get_chatwoot_connection(org_id)
        base_url, account_id, token = _resolve_chatwoot_config(conn)
        headers = {"api_access_token": token, "Content-Type": "application/json"}
        conv_url = f"{base_url}/api/v1/accounts/{account_id}/conversations/{conversation_id}"

        async with httpx.AsyncClient(timeout=10) as client:
            # GET current labels
            resp = await client.get(conv_url, headers=headers)
            resp.raise_for_status()
            current_labels = resp.json().get("labels", [])

            log.info(
                "[PIPELINE:LABEL:GET] Conv %s: labels atuais = %s",
                conversation_id, current_labels,
            )

            # Remove old stage labels, add new one
            removed = [l for l in current_labels if l in STAGE_LABELS]
            new_labels = [l for l in current_labels if l not in STAGE_LABELS]
            if new_label not in new_labels:
                new_labels.append(new_label)

            if removed:
                log.info(
                    "[PIPELINE:LABEL:SWAP] Conv %s: removendo %s, adicionando '%s'",
                    conversation_id, removed, new_label,
                )

            # PATCH conversation with updated labels
            resp = await client.patch(
                conv_url,
                json={"labels": new_labels},
                headers=headers,
            )
            resp.raise_for_status()

        log.info(
            "[PIPELINE:LABEL] Conv %s: labels finais = %s",
            conversation_id, new_labels,
        )
        return True

    except Exception as exc:
        log.error(
            "[PIPELINE:LABEL] Failed to swap label on conv %s: %s",
            conversation_id, exc,
        )
        return False


async def add_label_to_chatwoot(
    org_id: str,
    conversation_id: str,
    label: str,
) -> bool:
    """Add a non-stage label to a Chatwoot conversation (additive, no removal).

    For stage labels, use update_stage() instead.
    """
    try:
        conn = await sb.get_chatwoot_connection(org_id)
        base_url, account_id, token = _resolve_chatwoot_config(conn)
        headers = {"api_access_token": token, "Content-Type": "application/json"}
        conv_url = f"{base_url}/api/v1/accounts/{account_id}/conversations/{conversation_id}"

        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(conv_url, headers=headers)
            resp.raise_for_status()
            current_labels = resp.json().get("labels", [])

            if label in current_labels:
                return True

            new_labels = current_labels + [label]
            resp = await client.patch(
                conv_url,
                json={"labels": new_labels},
                headers=headers,
            )
            resp.raise_for_status()

        log.info("[PIPELINE] Label '%s' added to conv %s", label, conversation_id)
        return True

    except Exception as exc:
        log.error("[PIPELINE] Failed to add label '%s' to conv %s: %s", label, conversation_id, exc)
        return False


# ── Unified update function ──────────────────────────────────────────────

async def update_stage(
    org_id: str,
    contact_phone: str,
    conversation_id: str,
    stage_label: str,
    contact_name: str = "",
) -> bool:
    """Unified pipeline update: ensure deal + move stage + swap Chatwoot label.

    Args:
        org_id: Organization ID.
        contact_phone: Contact's phone number.
        conversation_id: Chatwoot conversation ID.
        stage_label: Chatwoot label OR pipeline stage key.
            Labels: novo_lead, qualificado, lead_quente, reuniao_agendada,
                    em_negociacao, fechou, perdido.
            Stage keys: primeiro_contato, qualificado, oportunidade, agendado,
                        negociacao, ganho, perdido.
        contact_name: Contact name (for creating new contacts/deals).
    """
    # Resolve stage key and Chatwoot label
    if stage_label in LABEL_TO_STAGE:
        label = stage_label
        stage_key = LABEL_TO_STAGE[stage_label]
    elif stage_label in STAGE_TO_LABEL:
        stage_key = stage_label
        label = STAGE_TO_LABEL[stage_label]
    else:
        # Unknown — use as both
        stage_key = stage_label
        label = stage_label

    log.info(
        "[PIPELINE] update_stage: phone=%s conv=%s label='%s' stage_key='%s'",
        contact_phone, conversation_id, label, stage_key,
    )

    success = True

    # 1. Move deal in CRM pipeline (creates contact+deal if needed)
    try:
        moved = await move_deal_to_stage(org_id, contact_phone, stage_key, contact_name)
        if not moved:
            success = False
    except Exception as exc:
        log.error("[PIPELINE] move_deal_to_stage failed: %s", exc)
        success = False

    # 2. Swap label in Chatwoot
    try:
        if label in STAGE_LABELS:
            await _swap_chatwoot_label(org_id, conversation_id, label)
        else:
            await add_label_to_chatwoot(org_id, conversation_id, label)
    except Exception as exc:
        log.error("[PIPELINE] label swap failed: %s", exc)
        success = False

    return success
