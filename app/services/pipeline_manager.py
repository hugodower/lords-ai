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
    channel: str = "WhatsApp",
) -> Optional[dict]:
    """Find or create contact with deduplication.

    Search order: phone → chatwoot_contact_id/chatwoot_id.
    If found by alternate criteria, updates missing phone/chatwoot_id.
    """
    digits = _normalize_phone(phone)
    log.info(
        "[PIPELINE:CONTACT:SEARCH] org=%s phone='%s' digits='%s' chatwoot_id='%s' name='%s'",
        org_id, phone, digits, chatwoot_contact_id, name,
    )

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
    log.info("[PIPELINE:CONTACT:CREATE] Creating new contact: name='%s' phone='%s' channel='%s'", name, digits, channel)
    contact = await sb.create_contact(
        org_id=org_id,
        name=name or "Sem nome",
        phone=phone,
        source=channel.lower(),
        chatwoot_contact_id=chatwoot_contact_id,
        channel=channel,
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
        log.info("[PIPELINE:DEAL:FOUND] deal=%s contact=%s status=%s", deal["id"], contact_id, deal.get("status"))
        return deal, False

    stages = await sb.get_pipeline_stages(org_id)
    if not stages:
        log.warning("[PIPELINE:DEAL] No pipeline/stages for org=%s — cannot create deal", org_id)
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
            "[PIPELINE:DEAL:CREATE] Deal criado na etapa '%s' (id=%s)",
            first_stage.get("name"), deal["id"],
        )
    return deal, True


# ── Chatwoot label management ────────────────────────────────────────────

async def swap_chatwoot_label(
    org_id: str,
    conversation_id: str,
    new_label: str,
) -> bool:
    """Replace stage labels with new_label (removes old stage labels first)."""
    log.info("[PIPELINE:SWAP:START] conv=%s new_label='%s' org=%s", conversation_id, new_label, org_id)
    try:
        conn = await sb.get_chatwoot_connection_cached(org_id)
        base_url, account_id, token = _resolve_chatwoot_config(conn)
        log.info(
            "[PIPELINE:SWAP:CONN] base_url=%s account_id=%s token_present=%s conn_from=%s",
            base_url, account_id, bool(token), "db" if conn else "global",
        )
        headers = {"api_access_token": token, "Content-Type": "application/json"}
        conv_url = f"{base_url}/api/v1/accounts/{account_id}/conversations/{conversation_id}"

        async with httpx.AsyncClient(timeout=10) as client:
            # GET current labels
            resp = await client.get(conv_url, headers=headers)
            log.info("[PIPELINE:SWAP:GET] url=%s status=%s", conv_url, resp.status_code)
            if resp.status_code != 200:
                log.error("[PIPELINE:SWAP:FAIL] GET failed: %s", resp.text[:300])
                return False
            resp.raise_for_status()
            current_labels = resp.json().get("labels", [])
            log.info("[PIPELINE:SWAP:CURRENT] conv=%s labels=%s", conversation_id, current_labels)

            # Build new labels list
            removed = [l for l in current_labels if l in STAGE_LABELS]
            new_labels = [l for l in current_labels if l not in STAGE_LABELS]
            if new_label not in new_labels:
                new_labels.append(new_label)

            if removed:
                log.info("[PIPELINE:SWAP:REMOVING] conv=%s removing=%s", conversation_id, removed)

            # PATCH new labels
            resp2 = await client.patch(conv_url, json={"labels": new_labels}, headers=headers)
            log.info(
                "[PIPELINE:SWAP:PATCH] conv=%s new_labels=%s status=%s",
                conversation_id, new_labels, resp2.status_code,
            )
            if resp2.status_code != 200:
                log.error("[PIPELINE:SWAP:FAIL] PATCH failed: %s", resp2.text[:300])
                return False
            resp2.raise_for_status()

        log.info("[PIPELINE:SWAP:OK] conv=%s label='%s' applied successfully", conversation_id, new_label)
        return True
    except Exception as exc:
        log.error("[PIPELINE:SWAP:ERROR] conv=%s label='%s' error=%s", conversation_id, new_label, exc)
        return False


async def add_label_to_chatwoot(
    org_id: str,
    conversation_id: str,
    label: str,
) -> bool:
    """Add a non-stage label (additive). For stage labels use swap_chatwoot_label()."""
    try:
        conn = await sb.get_chatwoot_connection_cached(org_id)
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


# ── Team assignment ──────────────────────────────────────────────────────

_team_cache: dict[str, int] = {}


async def assign_team(
    org_id: str,
    conversation_id: str,
    team_name: str = "comercial",
) -> bool:
    """Assign a Chatwoot team to a conversation."""
    try:
        conn = await sb.get_chatwoot_connection_cached(org_id)
        base_url, account_id, token = _resolve_chatwoot_config(conn)
        headers = {"api_access_token": token, "Content-Type": "application/json"}

        # Cache team_id lookup
        cache_key = f"{org_id}:{team_name}"
        if cache_key not in _team_cache:
            url = f"{base_url}/api/v1/accounts/{account_id}/teams"
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(url, headers=headers)
                if resp.status_code == 200:
                    for team in resp.json():
                        if team.get("name", "").lower() == team_name.lower():
                            _team_cache[cache_key] = team["id"]
                            break

        team_id = _team_cache.get(cache_key)
        if not team_id:
            log.warning("[PIPELINE:TEAM] Team '%s' not found for org=%s", team_name, org_id)
            return False

        url = f"{base_url}/api/v1/accounts/{account_id}/conversations/{conversation_id}/assignments"
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(url, json={"team_id": team_id}, headers=headers)
            log.info(
                "[PIPELINE:TEAM] Conv %s assigned to '%s' (team_id=%s) status=%s",
                conversation_id, team_name, team_id, resp.status_code,
            )
            return resp.status_code in (200, 201)
    except Exception as exc:
        log.error("[PIPELINE:TEAM:ERROR] %s", exc)
        return False


# ── Priority management ──────────────────────────────────────────────────

_PRIORITY_MAP = {
    "frustrated": "urgent",
    "urgent": "urgent",
    "negative": "high",
    "positive": "medium",
    "neutral": None,
}


async def set_priority(
    org_id: str,
    conversation_id: str,
    sentiment: str,
) -> bool:
    """Set conversation priority based on sentiment."""
    priority = _PRIORITY_MAP.get(sentiment)
    if not priority:
        return False

    try:
        conn = await sb.get_chatwoot_connection_cached(org_id)
        base_url, account_id, token = _resolve_chatwoot_config(conn)
        headers = {"api_access_token": token, "Content-Type": "application/json"}
        url = f"{base_url}/api/v1/accounts/{account_id}/conversations/{conversation_id}"

        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.patch(url, json={"priority": priority}, headers=headers)
            log.info(
                "[PIPELINE:PRIORITY] Conv %s priority=%s (sentiment=%s) status=%s",
                conversation_id, priority, sentiment, resp.status_code,
            )
            return resp.status_code == 200
    except Exception as exc:
        log.error("[PIPELINE:PRIORITY:ERROR] %s", exc)
        return False


# ── Unified update function ──────────────────────────────────────────────

async def update_stage(
    org_id: str,
    contact_phone: str,
    conversation_id: str,
    stage_label: str,
    contact_name: str = "",
    chatwoot_contact_id: str = "",
    channel: str = "WhatsApp",
) -> bool:
    """Ensure contact+deal exist, then swap the Chatwoot label.

    The CRM automation rules handle moving deals based on labels.
    """
    if stage_label not in STAGE_LABELS:
        log.warning("[PIPELINE] Unknown stage_label='%s' — skipping (valid: %s)", stage_label, STAGE_LABELS)
        return False

    log.info(
        "[PIPELINE:UPDATE_STAGE] org=%s phone='%s' conv=%s label='%s' name='%s' chatwoot_id='%s'",
        org_id, contact_phone, conversation_id, stage_label, contact_name, chatwoot_contact_id,
    )

    # Ensure contact exists
    contact = await ensure_contact_exists(org_id, contact_phone, contact_name, chatwoot_contact_id, channel=channel)
    if not contact:
        log.error("[PIPELINE:UPDATE_STAGE] Could not find/create contact for phone='%s'", contact_phone)
        return False

    # Ensure deal exists
    deal, _ = await ensure_deal_exists(org_id, contact["id"])
    if not deal:
        log.error("[PIPELINE:UPDATE_STAGE] Could not find/create deal for contact=%s", contact["id"])
        return False

    # Swap label — CRM automation handles the rest
    result = await swap_chatwoot_label(org_id, conversation_id, stage_label)
    log.info("[PIPELINE:UPDATE_STAGE] Result: label='%s' conv=%s success=%s", stage_label, conversation_id, result)
    return result


async def ensure_contact_and_deal(
    org_id: str,
    contact_phone: str,
    contact_name: str = "",
    chatwoot_contact_id: str = "",
    conversation_id: str = "",
    channel: str = "WhatsApp",
) -> None:
    """Ensure contact+deal exist. Adds novo_lead label only for new deals.

    Called on every message (the 'else' branch). Does NOT change labels on existing deals.
    """
    try:
        contact = await ensure_contact_exists(org_id, contact_phone, contact_name, chatwoot_contact_id, channel=channel)
        if not contact:
            return

        deal, is_new = await ensure_deal_exists(org_id, contact["id"])

        if is_new and conversation_id:
            await swap_chatwoot_label(org_id, conversation_id, "novo_lead")
            log.info("[PIPELINE] First contact — novo_lead label set for conv %s", conversation_id)
            # Assign team on first contact
            try:
                await assign_team(org_id, conversation_id)
            except Exception as team_err:
                log.warning("[PIPELINE:TEAM] Failed to assign team on new deal: %s", team_err)
    except Exception as exc:
        log.error("[PIPELINE] ensure_contact_and_deal error: %s", exc)
