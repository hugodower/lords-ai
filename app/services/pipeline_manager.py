"""Pipeline manager — auto-move deals through CRM stages based on Aurora's actions.

Creates contacts and deals automatically when they don't exist yet.
Deduplicates contacts by phone / chatwoot_contact_id.
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


# ── Exact stage name mapping (from real Supabase data) ───────────────────
# Label (Chatwoot)  →  exact pipeline stage name in DB
STAGE_MAP = {
    "novo_lead": "Prospecção",
    "qualificado": "Qualificação",
    "lead_quente": "Qualificação",
    "reuniao_agendada": "Reunião Agendada",
    "proposta": "Proposta",
    "em_negociacao": "Negociação",
    "fechou": "Fechamento",
    "perdido": "Prospecção",
}

# Mutually exclusive stage labels in Chatwoot
STAGE_LABELS = {
    "novo_lead", "qualificado", "lead_quente",
    "reuniao_agendada", "proposta", "em_negociacao", "fechou", "perdido",
}

# Fallback regex patterns (for orgs with different stage names)
_STAGE_PATTERNS = {
    "Prospecção": [r"prospec", r"novo", r"new"],
    "Qualificação": [r"qualificad", r"qualified"],
    "Reunião Agendada": [r"reuni", r"agendad", r"meeting", r"scheduled"],
    "Proposta": [r"propost", r"proposal"],
    "Negociação": [r"negocia", r"negotiat"],
    "Fechamento": [r"fecham", r"closing", r"ganh", r"won"],
}


def _normalize_phone(phone: str) -> str:
    """Strip to digits only."""
    return re.sub(r"\D", "", phone.strip()) if phone else ""


# ── Stage lookup ─────────────────────────────────────────────────────────

def _find_stage_by_name(stages: list[dict], target_name: str) -> Optional[dict]:
    """Find a stage by exact name, then fallback to regex pattern."""
    if not stages:
        return None

    # 1) Exact match
    for s in stages:
        if s.get("name") == target_name:
            return s

    # 2) Case-insensitive exact match
    target_lower = target_name.lower()
    for s in stages:
        if (s.get("name") or "").lower() == target_lower:
            return s

    # 3) Regex pattern fallback
    patterns = _STAGE_PATTERNS.get(target_name, [])
    for s in stages:
        name = (s.get("name") or "").lower()
        for pattern in patterns:
            if re.search(pattern, name, re.IGNORECASE):
                return s

    return None


# ── Chatwoot config helper ───────────────────────────────────────────────

def _resolve_chatwoot_config(conn: dict | None) -> tuple[str, int, str]:
    """Return (base_url, account_id, token) from connection or global settings."""
    base_url = settings.chatwoot_url.rstrip("/")
    account_id = settings.chatwoot_account_id
    token = settings.chatwoot_api_token

    if conn:
        base_url = (
            conn.get("base_url") or conn.get("chatwoot_base_url") or base_url
        ).rstrip("/")
        account_id = conn.get("chatwoot_account_id") or account_id
        token = conn.get("api_access_token") or conn.get("chatwoot_api_token") or token

    return base_url, account_id, token


# ── Contact deduplication + creation ─────────────────────────────────────

async def ensure_contact_exists(
    org_id: str,
    phone: str,
    name: str = "",
    chatwoot_contact_id: str = "",
) -> Optional[dict]:
    """Find or create contact with deduplication.

    Search order: phone → chatwoot_contact_id/chatwoot_id.
    If found by alternate criteria, updates missing phone/chatwoot_id.
    """
    digits = _normalize_phone(phone)

    # 1) Search by phone
    contact = await sb.find_contact_by_phone(org_id, phone) if digits else None
    if contact:
        log.info(
            "[PIPELINE:CONTACT:FOUND] Contato encontrado: %s (id=%s, phone=%s)",
            contact.get("name"), contact["id"], contact.get("phone"),
        )
        # Update chatwoot_id if we have it and contact doesn't
        if chatwoot_contact_id and not contact.get("chatwoot_contact_id"):
            await sb.update_contact_fields(contact["id"], {
                "chatwoot_contact_id": str(chatwoot_contact_id),
            })
        return contact

    # 2) Search by chatwoot_contact_id
    if chatwoot_contact_id:
        contact = await sb.find_contact_by_chatwoot_id(org_id, chatwoot_contact_id)
        if contact:
            log.info(
                "[PIPELINE:CONTACT:DEDUP] Contato encontrado por chatwoot_id=%s (id=%s, phone=%s)",
                chatwoot_contact_id, contact["id"], contact.get("phone"),
            )
            # Update phone if contact doesn't have one
            updates: dict = {}
            if digits and not contact.get("phone"):
                updates["phone"] = digits
            if name and contact.get("name") in (None, "", "Sem nome"):
                updates["name"] = name
            if updates:
                await sb.update_contact_fields(contact["id"], updates)
                log.info("[PIPELINE:CONTACT:DEDUP] Atualizando campos: %s", list(updates.keys()))
            return contact

    # 3) Not found — create
    contact = await sb.create_contact(
        org_id=org_id,
        name=name or "Sem nome",
        phone=phone,
        source="whatsapp",
        chatwoot_contact_id=chatwoot_contact_id,
    )
    return contact


# ── Deal creation ────────────────────────────────────────────────────────

async def ensure_deal_exists(
    org_id: str,
    contact_id: str,
) -> tuple[Optional[dict], bool]:
    """Find or create deal for contact. Returns (deal, is_new)."""
    # Find existing deal
    deal = await sb.find_deal_for_contact(org_id, contact_id)
    if deal:
        return deal, False

    # Create in first stage of default pipeline
    stages = await sb.get_pipeline_stages(org_id)
    if not stages:
        log.warning("[PIPELINE] No pipeline/stages for org=%s — cannot create deal", org_id)
        return None, False

    first_stage = stages[0]
    pipeline_id = first_stage["pipeline_id"]
    stage_id = first_stage["id"]

    deal = await sb.create_deal(
        org_id=org_id,
        contact_id=contact_id,
        pipeline_id=pipeline_id,
        stage_id=stage_id,
    )
    if deal:
        log.info(
            "[PIPELINE:DEAL:CREATE] Deal criado na etapa '%s' (pipeline=%s)",
            first_stage.get("name"), pipeline_id,
        )
    return deal, True


# ── Chatwoot label management ────────────────────────────────────────────

async def _swap_chatwoot_label(
    org_id: str,
    conversation_id: str,
    new_label: str,
) -> bool:
    """Replace stage labels with new_label (removes old stage labels first)."""
    try:
        conn = await sb.get_chatwoot_connection(org_id)
        base_url, account_id, token = _resolve_chatwoot_config(conn)
        headers = {"api_access_token": token, "Content-Type": "application/json"}
        conv_url = f"{base_url}/api/v1/accounts/{account_id}/conversations/{conversation_id}"

        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(conv_url, headers=headers)
            resp.raise_for_status()
            current_labels = resp.json().get("labels", [])

            log.info("[PIPELINE:LABEL:GET] Conv %s: labels atuais = %s", conversation_id, current_labels)

            removed = [l for l in current_labels if l in STAGE_LABELS]
            new_labels = [l for l in current_labels if l not in STAGE_LABELS]
            if new_label not in new_labels:
                new_labels.append(new_label)

            if removed:
                log.info(
                    "[PIPELINE:LABEL:SWAP] Conv %s: %s -> '%s'",
                    conversation_id, removed, new_label,
                )

            resp = await client.patch(conv_url, json={"labels": new_labels}, headers=headers)
            resp.raise_for_status()

        return True
    except Exception as exc:
        log.error("[PIPELINE:LABEL] Failed to swap label on conv %s: %s", conversation_id, exc)
        return False


async def add_label_to_chatwoot(
    org_id: str,
    conversation_id: str,
    label: str,
) -> bool:
    """Add a non-stage label (additive). For stage labels use update_stage()."""
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
            resp = await client.patch(conv_url, json={"labels": new_labels}, headers=headers)
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
    chatwoot_contact_id: str = "",
) -> bool:
    """Unified pipeline update: ensure contact+deal + move stage + swap label.

    Args:
        stage_label: Chatwoot label (novo_lead, qualificado, lead_quente,
                     reuniao_agendada, proposta, em_negociacao, fechou, perdido).
    """
    log.info(
        "[PIPELINE] update_stage: phone=%s conv=%s label='%s' name='%s'",
        contact_phone, conversation_id, stage_label, contact_name,
    )

    # 1. Resolve target stage name
    target_stage_name = STAGE_MAP.get(stage_label)
    if not target_stage_name:
        log.warning("[PIPELINE] Unknown stage_label='%s' — skipping", stage_label)
        return False

    # 2. Ensure contact exists
    contact = await ensure_contact_exists(org_id, contact_phone, contact_name, chatwoot_contact_id)
    if not contact:
        log.error("[PIPELINE] Could not find/create contact for phone=%s", contact_phone)
        return False

    contact_id = contact["id"]

    # 3. Ensure deal exists
    deal, is_new = await ensure_deal_exists(org_id, contact_id)
    if not deal:
        log.error("[PIPELINE] Could not find/create deal for contact=%s", contact_id)
        return False

    deal_id = deal["id"]
    pipeline_id = deal.get("pipeline_id")
    current_stage_id = deal.get("stage_id")

    # 4. Find target stage by exact name
    stages = await sb.get_pipeline_stages(org_id, pipeline_id)
    if not stages:
        log.warning("[PIPELINE] No stages for pipeline=%s", pipeline_id)
        return False

    target = _find_stage_by_name(stages, target_stage_name)
    if not target:
        log.warning(
            "[PIPELINE] Stage '%s' not found (available: %s)",
            target_stage_name, [s.get("name") for s in stages],
        )
        return False

    target_stage_id = target["id"]

    # 5. Move deal if not already in target stage
    if current_stage_id != target_stage_id:
        current_name = "?"
        for s in stages:
            if s["id"] == current_stage_id:
                current_name = s.get("name", "?")
                break

        success = await sb.update_deal_stage(deal_id, target_stage_id)
        if success:
            log.info(
                "[PIPELINE:DEAL:MOVE] Deal %s movido de '%s' para '%s'",
                deal_id, current_name, target.get("name"),
            )
            if stage_label == "perdido":
                await sb.update_deal_lost(deal_id)

    # 6. Swap Chatwoot label
    try:
        await _swap_chatwoot_label(org_id, conversation_id, stage_label)
    except Exception as exc:
        log.error("[PIPELINE] Label swap failed: %s", exc)

    return True


async def ensure_contact_and_deal(
    org_id: str,
    contact_phone: str,
    contact_name: str = "",
    chatwoot_contact_id: str = "",
    conversation_id: str = "",
) -> None:
    """Ensure contact+deal exist. Adds novo_lead label only for new deals.

    Called on every message (the 'else' branch). Does NOT downgrade existing deals.
    """
    try:
        contact = await ensure_contact_exists(org_id, contact_phone, contact_name, chatwoot_contact_id)
        if not contact:
            return

        deal, is_new = await ensure_deal_exists(org_id, contact["id"])

        if is_new and conversation_id:
            await _swap_chatwoot_label(org_id, conversation_id, "novo_lead")
            log.info("[PIPELINE] First contact — novo_lead label set for conv %s", conversation_id)
    except Exception as exc:
        log.error("[PIPELINE] ensure_contact_and_deal error: %s", exc)
