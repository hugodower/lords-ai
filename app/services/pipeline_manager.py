"""Pipeline manager — Aurora only manages Chatwoot labels.

The CRM has automation rules that move deals based on labels.
Aurora's job: ensure contact+deal exist, then swap the label.
"""
from __future__ import annotations

import re
from typing import Optional

import httpx

from app.config import settings
from app.integrations import supabase_client as sb
from app.utils.logger import get_logger

log = get_logger("pipeline")


# Mutually exclusive stage labels in Chatwoot (exact names)
STAGE_LABELS = {
    "novo_lead", "qualificado", "reuniao_agendada",
    "proposta_enviada", "em_negociacao", "fechou", "perdeu",
}


def _normalize_phone(phone: str) -> str:
    """Strip to digits only."""
    return re.sub(r"\D", "", phone.strip()) if phone else ""


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
            "[PIPELINE:CONTACT:FOUND] %s (id=%s, phone=%s)",
            contact.get("name"), contact["id"], contact.get("phone"),
        )
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
                "[PIPELINE:CONTACT:DEDUP] chatwoot_id=%s (id=%s)",
                chatwoot_contact_id, contact["id"],
            )
            updates: dict = {}
            if digits and not contact.get("phone"):
                updates["phone"] = digits
            if name and contact.get("name") in (None, "", "Sem nome"):
                updates["name"] = name
            if updates:
                await sb.update_contact_fields(contact["id"], updates)
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
    deal = await sb.find_deal_for_contact(org_id, contact_id)
    if deal:
        return deal, False

    stages = await sb.get_pipeline_stages(org_id)
    if not stages:
        log.warning("[PIPELINE] No pipeline/stages for org=%s", org_id)
        return None, False

    first_stage = stages[0]
    deal = await sb.create_deal(
        org_id=org_id,
        contact_id=contact_id,
        pipeline_id=first_stage["pipeline_id"],
        stage_id=first_stage["id"],
    )
    if deal:
        log.info(
            "[PIPELINE:DEAL:CREATE] Deal criado na etapa '%s'",
            first_stage.get("name"),
        )
    return deal, True


# ── Chatwoot label management ────────────────────────────────────────────

async def swap_chatwoot_label(
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

            removed = [l for l in current_labels if l in STAGE_LABELS]
            new_labels = [l for l in current_labels if l not in STAGE_LABELS]
            if new_label not in new_labels:
                new_labels.append(new_label)

            if removed:
                log.info("[PIPELINE:LABEL:SWAP] Conv %s: %s -> '%s'", conversation_id, removed, new_label)

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
    """Add a non-stage label (additive). For stage labels use swap_chatwoot_label()."""
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
    """Ensure contact+deal exist, then swap the Chatwoot label.

    The CRM automation rules handle moving deals based on labels.
    """
    if stage_label not in STAGE_LABELS:
        log.warning("[PIPELINE] Unknown stage_label='%s' — skipping", stage_label)
        return False

    log.info(
        "[PIPELINE] update_stage: phone=%s conv=%s label='%s'",
        contact_phone, conversation_id, stage_label,
    )

    # Ensure contact exists
    contact = await ensure_contact_exists(org_id, contact_phone, contact_name, chatwoot_contact_id)
    if not contact:
        log.error("[PIPELINE] Could not find/create contact for phone=%s", contact_phone)
        return False

    # Ensure deal exists
    deal, _ = await ensure_deal_exists(org_id, contact["id"])
    if not deal:
        log.error("[PIPELINE] Could not find/create deal for contact=%s", contact["id"])
        return False

    # Swap label — CRM automation handles the rest
    await swap_chatwoot_label(org_id, conversation_id, stage_label)
    return True


async def ensure_contact_and_deal(
    org_id: str,
    contact_phone: str,
    contact_name: str = "",
    chatwoot_contact_id: str = "",
    conversation_id: str = "",
) -> None:
    """Ensure contact+deal exist. Adds novo_lead label only for new deals.

    Called on every message (the 'else' branch). Does NOT change labels on existing deals.
    """
    try:
        contact = await ensure_contact_exists(org_id, contact_phone, contact_name, chatwoot_contact_id)
        if not contact:
            return

        deal, is_new = await ensure_deal_exists(org_id, contact["id"])

        if is_new and conversation_id:
            await swap_chatwoot_label(org_id, conversation_id, "novo_lead")
            log.info("[PIPELINE] First contact — novo_lead label set for conv %s", conversation_id)
    except Exception as exc:
        log.error("[PIPELINE] ensure_contact_and_deal error: %s", exc)
