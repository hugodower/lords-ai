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
from app.utils.ddd_mapper import get_location_from_phone
from app.utils.logger import get_logger

log = get_logger("pipeline")


# Fallback labels — usadas apenas se label_mappings estiver vazio ou o Supabase
# falhar. Em produção, cada org define suas próprias labels via tabela
# label_mappings. Esse fallback preserva o comportamento da LORDS em caso
# de indisponibilidade do banco (safety net, não fonte de verdade).
# 'fechou' e 'perdeu' foram removidos — agora são representados via
# deals.status ('won' / 'lost'), não via label.
STAGE_LABELS_FALLBACK = {
    "01-novo-contato",
    "02-qualificacao",
    "03-reuniao-agendada",
    "04-proposta-enviada",
    "05-em-negociacao",
}


async def get_stage_labels(org_id: str) -> set[str]:
    """Retorna as stage labels válidas da org (lidas de label_mappings).

    Se a tabela estiver vazia ou o Supabase falhar, usa STAGE_LABELS_FALLBACK
    pra não quebrar organizações ativas. Log de warning pra rastreabilidade.
    """
    try:
        mappings = await sb.get_label_mappings(org_id)
        labels = {m["chatwoot_label"] for m in mappings if m.get("chatwoot_label")}
        if not labels:
            log.warning(
                "[PIPELINE:LABELS] Empty label_mappings for org=%s — using fallback",
                org_id,
            )
            return STAGE_LABELS_FALLBACK
        return labels
    except Exception as exc:
        log.warning(
            "[PIPELINE:LABELS] Failed to load label_mappings for org=%s (%s) — using fallback",
            org_id, exc,
        )
        return STAGE_LABELS_FALLBACK


def _normalize_phone(phone: str) -> str:
    """Strip to digits only."""
    return re.sub(r"\D", "", phone.strip()) if phone else ""


def _label_to_position(stage_label: str) -> Optional[int]:
    """Extract numeric position from stage label like '03-reuniao-agendada' → 3.

    Returns None if label doesn't follow the 'NN-name' convention.
    """
    match = re.match(r'^(\d+)-', stage_label)
    return int(match.group(1)) if match else None


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
    """Find or create contact with cross-channel deduplication.

    Search order: phone → chatwoot_contact_id → exact name match.
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
        updates: dict = {}
        if chatwoot_contact_id and not contact.get("chatwoot_contact_id"):
            updates["chatwoot_contact_id"] = str(chatwoot_contact_id)
        if not contact.get("channel") and channel:
            updates["channel"] = sb._channel_to_lowercase(channel)
        if not contact.get("owner_user_id"):
            owner = await sb.get_org_default_owner(org_id)
            if owner:
                updates["owner_user_id"] = owner
        if not contact.get("city"):
            loc = get_location_from_phone(contact.get("phone") or phone)
            if loc:
                updates["city"] = loc["city"]
                updates["state"] = loc["state"]
                updates["country"] = loc["country"]
                log.info("[PIPELINE:LOCATION:BACKFILL] %s — %s/%s", contact.get("name"), loc["city"], loc["state"])
        if updates:
            await sb.update_contact_fields(contact["id"], updates)
        return contact

    # 2) Search by chatwoot_contact_id
    if chatwoot_contact_id:
        contact = await sb.find_contact_by_chatwoot_id(org_id, chatwoot_contact_id)
        if contact:
            log.info(
                "[PIPELINE:CONTACT:DEDUP] chatwoot_id=%s (id=%s, phone=%s)",
                chatwoot_contact_id, contact["id"], contact.get("phone"),
            )
            # Cross-channel merge: if this contact has no phone but another
            # contact with the same name DOES have a phone, prefer that one
            if name and name.strip() and not contact.get("phone"):
                better = await sb.find_contacts_by_name(org_id, name.strip())
                for b in better:
                    if b.get("phone") and b["id"] != contact["id"]:
                        log.info(
                            "[PIPELINE:CONTACT:MERGE] chatwoot_id=%s → merging into contact %s (has phone=%s)",
                            chatwoot_contact_id, b["id"], b.get("phone"),
                        )
                        return b
            updates: dict = {}
            if digits and not contact.get("phone"):
                updates["phone"] = digits
            if name and contact.get("name") in (None, "", "Sem nome"):
                updates["name"] = name
            if not contact.get("channel") and channel:
                updates["channel"] = sb._channel_to_lowercase(channel)
            if not contact.get("owner_user_id"):
                owner = await sb.get_org_default_owner(org_id)
                if owner:
                    updates["owner_user_id"] = owner
            if not contact.get("city"):
                loc = get_location_from_phone(contact.get("phone") or phone)
                if loc:
                    updates["city"] = loc["city"]
                    updates["state"] = loc["state"]
                    updates["country"] = loc["country"]
                    log.info("[PIPELINE:LOCATION:BACKFILL] %s — %s/%s", contact.get("name"), loc["city"], loc["state"])
            if updates:
                await sb.update_contact_fields(contact["id"], updates)
            return contact

    # 3) Search by exact name (last resort dedup)
    if name and name.strip():
        contacts = await sb.find_contacts_by_name(org_id, name.strip())
        if len(contacts) == 1:
            contact = contacts[0]
            log.info(
                "[PIPELINE:CONTACT:DEDUP_BY_NAME] Found '%s' by name match (id=%s)",
                name, contact["id"],
            )
            updates = {}
            if digits and not contact.get("phone"):
                updates["phone"] = digits
            if chatwoot_contact_id and not contact.get("chatwoot_contact_id"):
                updates["chatwoot_contact_id"] = str(chatwoot_contact_id)
            if not contact.get("channel") and channel:
                updates["channel"] = sb._channel_to_lowercase(channel)
            if not contact.get("owner_user_id"):
                owner = await sb.get_org_default_owner(org_id)
                if owner:
                    updates["owner_user_id"] = owner
            if not contact.get("city"):
                loc = get_location_from_phone(contact.get("phone") or phone)
                if loc:
                    updates["city"] = loc["city"]
                    updates["state"] = loc["state"]
                    updates["country"] = loc["country"]
                    log.info("[PIPELINE:LOCATION:BACKFILL] %s — %s/%s", contact.get("name"), loc["city"], loc["state"])
            if updates:
                await sb.update_contact_fields(contact["id"], updates)
            return contact
        elif len(contacts) > 1:
            # Multiple contacts with same name — prefer the one with phone
            with_phone = [c for c in contacts if c.get("phone")]
            if len(with_phone) == 1:
                log.info(
                    "[PIPELINE:CONTACT:DEDUP_PHONE_PRIORITY] Found '%s' with phone among %d namesakes (id=%s)",
                    name, len(contacts), with_phone[0]["id"],
                )
                return with_phone[0]
            log.warning(
                "[PIPELINE:CONTACT:AMBIGUOUS] Multiple contacts named '%s' (%d found), creating new",
                name, len(contacts),
            )

    # 4) Not found — create
    owner = await sb.get_org_default_owner(org_id)
    loc = get_location_from_phone(phone)
    log.info("[PIPELINE:CONTACT:CREATE] Creating new contact: name='%s' phone='%s' channel='%s' owner='%s'", name, digits, channel, owner or "—")
    if loc:
        log.info("[PIPELINE:LOCATION] %s — %s/%s (DDD from phone)", name or "Sem nome", loc["city"], loc["state"])
    contact = await sb.create_contact(
        org_id=org_id,
        name=name or "Sem nome",
        phone=phone,
        source=channel.lower(),
        chatwoot_contact_id=chatwoot_contact_id,
        channel=channel,
        owner_user_id=owner or "",
        city=loc["city"] if loc else "",
        state=loc["state"] if loc else "",
        country=loc["country"] if loc else "",
    )
    return contact


# ── Deal creation ────────────────────────────────────────────────────────

async def ensure_deal_exists(
    org_id: str,
    contact_id: str,
    contact_name: str = "",
) -> tuple[Optional[dict], bool]:
    """Find or create deal for contact. Returns (deal, is_new)."""
    deal = await sb.find_deal_for_contact(org_id, contact_id)
    if deal:
        log.info("[PIPELINE:DEAL:FOUND] deal=%s contact=%s status=%s", deal["id"], contact_id, deal.get("status"))
        return deal, False

    # Check if another contact with the same name has an open deal
    if contact_name and contact_name.strip():
        try:
            contacts = await sb.find_contacts_by_name(org_id, contact_name.strip())
            for c in contacts:
                if c["id"] != contact_id:
                    alt_deal = await sb.find_deal_for_contact(org_id, c["id"])
                    if alt_deal:
                        log.info(
                            "[PIPELINE:DEAL:FOUND_BY_NAME] Deal %s found via name match '%s' (alt_contact=%s)",
                            alt_deal["id"], contact_name, c["id"],
                        )
                        return alt_deal, False
        except Exception as exc:
            log.warning("[PIPELINE:DEAL:NAME_SEARCH_ERROR] %s", exc)

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

            # Build new labels list (stage labels são mutuamente exclusivas)
            stage_labels = await get_stage_labels(org_id)
            removed = [l for l in current_labels if l in stage_labels]
            new_labels = [l for l in current_labels if l not in stage_labels]
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
    stage_labels = await get_stage_labels(org_id)
    if stage_label not in stage_labels:
        log.warning(
            "[PIPELINE] Unknown stage_label='%s' for org=%s — skipping (valid: %s)",
            stage_label, org_id, sorted(stage_labels),
        )
        return False

    log.info(
        "[PIPELINE:UPDATE_STAGE] org=%s phone='%s' conv=%s label='%s' name='%s' chatwoot_id='%s'",
        org_id, contact_phone, conversation_id, stage_label, contact_name, chatwoot_contact_id,
    )

    # Guard contra retrocesso automático (Risco 1 / Bloco 3)
    # Comparação SOMENTE por position — ignora nome/label.
    current = await get_current_stage(org_id, contact_phone)
    if current and current.get("position") is not None:
        target_position = _get_stage_position_by_chatwoot_label(org_id, stage_label)
        if target_position is not None and target_position < current["position"]:
            log.warning(
                "[STAGE:REGRESSION_BLOCKED] %s | atual=%s(pos=%d) tentou=%s(pos=%d) — recusado",
                contact_phone,
                current["name"],
                current["position"],
                stage_label,
                target_position,
            )
            return False  # recusa silenciosamente, segue o fluxo

    # Ensure contact exists
    contact = await ensure_contact_exists(org_id, contact_phone, contact_name, chatwoot_contact_id, channel=channel)
    if not contact:
        log.error("[PIPELINE:UPDATE_STAGE] Could not find/create contact for phone='%s'", contact_phone)
        return False

    # Ensure deal exists
    deal, _ = await ensure_deal_exists(org_id, contact["id"], contact_name=contact_name)
    if not deal:
        log.error("[PIPELINE:UPDATE_STAGE] Could not find/create deal for contact=%s", contact["id"])
        return False

    # Swap label in Chatwoot
    result = await swap_chatwoot_label(org_id, conversation_id, stage_label)
    log.info("[PIPELINE:UPDATE_STAGE] Result: label='%s' conv=%s success=%s", stage_label, conversation_id, result)

    # If Chatwoot swap succeeded, also update deals.stage_id in Supabase
    if result:
        position = _label_to_position(stage_label)
        if position is not None:
            try:
                stages = await sb.get_pipeline_stages(org_id)
                target_stage = next((s for s in stages if s.get("position") == position), None)
                if target_stage:
                    stage_id = target_stage["id"]
                    await sb.update_deal_stage(deal["id"], stage_id)
                    log.info(
                        "[PIPELINE:UPDATE_STAGE:CRM] Deal %s moved to stage_id=%s (position=%d, label='%s')",
                        deal["id"], stage_id, position, stage_label,
                    )
                else:
                    log.warning(
                        "[PIPELINE:UPDATE_STAGE:CRM] No stage found for position=%d in org=%s",
                        position, org_id,
                    )
            except Exception as exc:
                log.error(
                    "[PIPELINE:UPDATE_STAGE:CRM] Failed to update deal=%s for org=%s: %s",
                    deal["id"], org_id, exc,
                )
        else:
            log.debug(
                "[PIPELINE:UPDATE_STAGE:CRM] Label '%s' has no numeric prefix — skipping CRM stage update",
                stage_label,
            )

    return result


async def get_current_stage(org_id: str, phone: str) -> dict | None:
    """
    Busca o stage atual do deal ativo de um contato.

    Reaproveita find_contact_by_phone e find_deal_for_contact (já existentes no supabase_client).
    Faz a query de pipeline_stages inline (mesmo padrão da query existente neste módulo).

    Retorna:
        {"name": "02. Qualificação", "position": 2} se encontrar deal ativo
        None se não houver contato/deal/stage, ou se houver erro

    NÃO levanta exceção — em caso de erro, loga e retorna None.
    """
    try:
        # 1. Buscar contato pelo phone (função já existente no supabase_client)
        contact = await sb.find_contact_by_phone(org_id, phone)
        if not contact:
            log.info("[STAGE:GET] Sem contato para %s na org %s", phone, org_id)
            return None

        # 2. Buscar deal ativo do contato (função já existente no supabase_client)
        deal = await sb.find_deal_for_contact(org_id, contact["id"])
        if not deal or not deal.get("stage_id"):
            log.info("[STAGE:GET] Sem deal ativo para contact %s", contact["id"])
            return None

        # 3. Buscar stage no pipeline_stages (mesma query que já existe na linha ~869)
        # Usa o helper privado _get_stage_by_id (a ser criado na Mudança 2)
        stage = await _get_stage_by_id(org_id, deal["stage_id"])
        if not stage:
            log.warning("[STAGE:GET] Stage %s não encontrado", deal["stage_id"])
            return None

        result = {
            "name": stage.get("name"),
            "position": stage.get("position"),
        }
        log.info("[STAGE:GET] %s está em %s (position %s)", phone, result["name"], result["position"])
        return result

    except Exception as e:
        log.error("[STAGE:GET:ERROR] Falha ao buscar stage de %s: %s", phone, str(e))
        return None


async def _get_stage_by_id(org_id: str, stage_id: str) -> dict | None:
    """
    Helper privado — busca um pipeline_stage pelo ID.

    Retorna dict com {id, name, position, pipeline_id} ou None.
    Reaproveita o padrão de query já existente neste módulo (sb.get_pipeline_stages).
    """
    try:
        # Pega todos os stages da org e filtra pelo ID
        # (aproveita o cache/otimização já existente em get_pipeline_stages)
        stages = await sb.get_pipeline_stages(org_id)
        for stage in stages:
            if stage.get("id") == stage_id:
                return stage

        log.warning("[STAGE:_get_by_id] Stage %s não encontrado para org %s", stage_id, org_id)
        return None
    except Exception as e:
        log.error("[STAGE:_get_by_id:ERROR] %s — stage_id=%s: %s", org_id, stage_id, str(e))
        return None


def _get_stage_position_by_chatwoot_label(org_id: str, chatwoot_label: str) -> int | None:
    """
    Helper privado — converte um chatwoot_label em position numérica.

    Usado pelo guard de retrocesso. Comparação é feita SOMENTE por position.

    O chatwoot_label vem no formato "02-qualificacao" (etiqueta do Chatwoot).
    Aproveita a função _label_to_position já existente que extrai o número do prefixo.

    Retorna a position (int) ou None se não seguir o formato 'NN-nome'.

    Nota: esta versão é síncrona e não precisa acessar o banco - aproveita
    a convenção de numeração já estabelecida no projeto.
    """
    return _label_to_position(chatwoot_label)


async def ensure_contact_and_deal(
    org_id: str,
    contact_phone: str,
    contact_name: str = "",
    chatwoot_contact_id: str = "",
    conversation_id: str = "",
    channel: str = "WhatsApp",
) -> None:
    """Ensure contact+deal exist. Adds 01-novo-contato label only for new deals.

    Called on every message (the 'else' branch). Does NOT change labels on existing deals.
    """
    try:
        contact = await ensure_contact_exists(org_id, contact_phone, contact_name, chatwoot_contact_id, channel=channel)
        if not contact:
            return

        deal, is_new = await ensure_deal_exists(org_id, contact["id"], contact_name=contact_name)

        if is_new and conversation_id:
            await swap_chatwoot_label(org_id, conversation_id, "01-novo-contato")
            log.info("[PIPELINE] First contact — 01-novo-contato label set for conv %s", conversation_id)
            # Assign team on first contact
            try:
                await assign_team(org_id, conversation_id)
            except Exception as team_err:
                log.warning("[PIPELINE:TEAM] Failed to assign team on new deal: %s", team_err)
    except Exception as exc:
        log.error("[PIPELINE] ensure_contact_and_deal error: %s", exc)


async def mark_deal_as_lost(
    org_id: str,
    contact_phone: str,
    reason: str = "unknown",
) -> bool:
    """Marca o deal ativo de um contato como perdido (status='lost').

    Substitui update_stage(..., "perdeu", ...) que dependia da label 'perdeu'
    (removida do banco da LORDS).

    Protege contra sobrescrever deals já fechados: se o deal mais recente
    do contato já estiver com status 'won' ou 'lost', loga warning e retorna False.

    Args:
        org_id: UUID da organização
        contact_phone: telefone normalizado do contato
        reason: motivo do lost (vai pra coluna loss_reason)

    Returns:
        True se atualizou, False se contato/deal não encontrado ou deal já fechado.
    """
    contact = await sb.find_contact_by_phone(org_id, contact_phone)
    if not contact:
        log.warning("[PIPELINE] mark_deal_as_lost: contato não encontrado phone=%s", contact_phone)
        return False

    deal = await sb.find_deal_for_contact(org_id, contact["id"])
    if not deal:
        log.warning("[PIPELINE] mark_deal_as_lost: nenhum deal para contact=%s", contact["id"])
        return False

    if deal.get("status") in ("won", "lost"):
        log.warning(
            "[PIPELINE] mark_deal_as_lost: deal %s já fechado (status=%s), ignorando",
            deal["id"], deal.get("status")
        )
        return False

    return await sb.update_deal_lost(deal["id"], reason=reason)


async def mark_deal_as_won(
    org_id: str,
    contact_phone: str,
    reason: str = "closed",
) -> bool:
    """Marca o deal ativo de um contato como ganho (status='won').

    Substitui update_stage(..., "fechou", ...) que dependia da label 'fechou'
    (removida do banco da LORDS).

    Protege contra sobrescrever deals já fechados.
    """
    contact = await sb.find_contact_by_phone(org_id, contact_phone)
    if not contact:
        log.warning("[PIPELINE] mark_deal_as_won: contato não encontrado phone=%s", contact_phone)
        return False

    deal = await sb.find_deal_for_contact(org_id, contact["id"])
    if not deal:
        log.warning("[PIPELINE] mark_deal_as_won: nenhum deal para contact=%s", contact["id"])
        return False

    if deal.get("status") in ("won", "lost"):
        log.warning(
            "[PIPELINE] mark_deal_as_won: deal %s já fechado (status=%s), ignorando",
            deal["id"], deal.get("status")
        )
        return False

    return await sb.update_deal_won(deal["id"], reason=reason)
