"""Long-term contact memory for Aurora.

Loads/saves structured memory about contacts so Aurora can remember
previous conversations even after days/weeks.
"""
from __future__ import annotations

import asyncio
import json
import re
from datetime import datetime, timedelta, timezone
from typing import Optional

from app.integrations import supabase_client as sb
from app.memory.redis_store import get_conversation_history
from app.utils.logger import get_logger

log = get_logger("memory")

BRT = timezone(timedelta(hours=-3))

# After 90 days of inactivity, reset qualification to cold
STALE_DAYS = 90

# Only update memory when conversation has this many messages
MIN_MESSAGES_FOR_UPDATE = 5

# Max summary length stored
MAX_SUMMARY_LENGTH = 500


def _phone_digits(phone: str) -> str:
    """Strip phone to digits only for contact_memory lookups."""
    return re.sub(r"\\D", "", phone)


# ── Load ────────────────────────────────────────────────────────────


async def load_contact_memory(
    org_id: str, contact_phone: str, chatwoot_contact_id: str = "",
) -> Optional[dict]:
    """Load existing memory for a contact. Returns None if first contact.

    Falls back to chatwoot_contact_id when phone is empty (non-WhatsApp channels).
    """
    phone = _phone_digits(contact_phone)
    if not phone and not chatwoot_contact_id:
        return None

    memory = await sb.get_contact_memory(org_id, phone, chatwoot_contact_id)
    if not memory:
        log.info("[MEMORY:LOAD] Sem memória para %s (primeiro contato)", contact_phone or f"cw:{chatwoot_contact_id}")
        return None

    # Check staleness — reset to cold if > 90 days
    last_at = memory.get("last_interaction_at")
    if last_at:
        try:
            last_dt = datetime.fromisoformat(last_at.replace("Z", "+00:00"))
            days_ago = (datetime.now(BRT) - last_dt).days
            memory["_days_since_last"] = days_ago

            if days_ago > STALE_DAYS:
                log.info(
                    "[MEMORY:LOAD] Memória stale (%d dias) para %s — resetando para cold",
                    days_ago, contact_phone,
                )
                memory["qualification_status"] = "cold"
        except Exception:
            memory["_days_since_last"] = None

    log.info(
        "[MEMORY:LOAD] Memória carregada para %s (última interação: %s dias atrás, status: %s)",
        contact_phone,
        memory.get("_days_since_last", "?"),
        memory.get("qualification_status", "?"),
    )

    # Increment conversations count and update last_interaction_at
    await sb.increment_contact_conversations(org_id, phone, chatwoot_contact_id)

    return memory


def format_memory_for_prompt(memory: dict) -> str:
    """Format contact memory as a section for the system prompt.

    Returns empty string if memory is None or empty (first contact).
    """
    if not memory:
        return ""

    parts = []

    name = memory.get("contact_name")
    if name:
        parts.append(f"- Nome: {name}")

    company = memory.get("contact_company")
    if company:
        parts.append(f"- Empresa: {company}")

    days = memory.get("_days_since_last")
    if days is not None:
        if days == 0:
            parts.append("- Última conversa: hoje")
        elif days == 1:
            parts.append("- Última conversa: ontem")
        else:
            parts.append(f"- Última conversa: há {days} dias")

    interests = memory.get("interests")
    if interests and isinstance(interests, list) and len(interests) > 0:
        parts.append(f"- Interesses: {', '.join(interests)}")

    status = memory.get("qualification_status")
    if status:
        status_labels = {
            "cold": "frio",
            "warm": "morno",
            "hot": "quente",
            "converted": "convertido",
            "lost": "perdido",
        }
        parts.append(f"- Status: {status_labels.get(status, status)}")

    total = memory.get("total_conversations", 0)
    if total and total > 1:
        parts.append(f"- Total de conversas anteriores: {total}")

    summary = memory.get("summary")
    if summary:
        parts.append(f"- Resumo: {summary}")

    if not parts:
        return ""

    return (
        "\n\n## MEMÓRIA DO CONTATO\n"
        "Este contato já conversou conosco antes. Aqui está o que sabemos:\n"
        + "\n".join(parts)
        + "\n\nUSE ESSAS INFORMAÇÕES NATURALMENTE na conversa. "
        "Não repita o resumo completo, mas referencie pontos relevantes quando fizer sentido. "
        "Demonstre que se lembra do contato de forma natural e acolhedora."
    )


# ── Save ────────────────────────────────────────────────────────────


async def maybe_update_memory(
    org_id: str,
    contact_phone: str,
    contact_name: str,
    conversation_id: str,
    action: str,
    lead_temperature: str = "cold",
    last_sentiment: str = "neutral",
    chatwoot_contact_id: str = "",
) -> None:
    """Check if memory should be updated, and do so in background.

    Called after Aurora processes a message. Runs the actual extraction
    as an asyncio task to avoid blocking the response.
    """
    # Always update on significant actions
    force = action in ("handoff", "schedule")

    if not force:
        # Only update if conversation has enough messages
        try:
            history = await get_conversation_history(conversation_id)
            msg_count = len(history)
            if msg_count < MIN_MESSAGES_FOR_UPDATE:
                return
        except Exception:
            return

    # Fire and forget — don't block the response
    asyncio.create_task(
        _do_update_memory(
            org_id=org_id,
            contact_phone=contact_phone,
            contact_name=contact_name,
            conversation_id=conversation_id,
            lead_temperature=lead_temperature,
            last_sentiment=last_sentiment,
            chatwoot_contact_id=chatwoot_contact_id,
        )
    )


async def _do_update_memory(
    org_id: str,
    contact_phone: str,
    contact_name: str,
    conversation_id: str,
    lead_temperature: str,
    last_sentiment: str = "neutral",
    chatwoot_contact_id: str = "",
) -> None:
    """Actually extract and save memory (runs as background task)."""
    try:
        phone = _phone_digits(contact_phone)
        if not phone and not chatwoot_contact_id:
            return

        # Get conversation history
        history = await get_conversation_history(conversation_id)
        if not history:
            return

        # Extract structured info using Haiku
        extracted = await _extract_memory(history)
        if not extracted:
            log.warning("[MEMORY:SAVE] Extraction returned nothing for conv %s", conversation_id)
            return

        # Override qualification from agent output if available
        if lead_temperature and lead_temperature != "cold":
            extracted["qualification_status"] = lead_temperature

        # Load existing memory for merge
        existing = await sb.get_contact_memory(org_id, phone, chatwoot_contact_id)

        # Merge
        merged = _merge_memory(existing, extracted)

        # Use contact_name from param if extraction didn't find one
        if not merged.get("contact_name") and contact_name:
            merged["contact_name"] = contact_name

        # Truncate summary
        if merged.get("summary") and len(merged["summary"]) > MAX_SUMMARY_LENGTH:
            merged["summary"] = merged["summary"][:MAX_SUMMARY_LENGTH]

        # Save sentiment in metadata
        meta = merged.get("metadata") or {}
        if isinstance(meta, str):
            try:
                meta = json.loads(meta)
            except Exception:
                meta = {}
        if last_sentiment and last_sentiment != "neutral":
            meta["last_sentiment"] = last_sentiment
            history_list = meta.get("sentiment_history") or []
            history_list.append(last_sentiment)
            meta["sentiment_history"] = history_list[-10:]  # Keep last 10
        merged["metadata"] = meta

        # Save
        merged["last_conversation_id"] = conversation_id
        merged["last_interaction_at"] = datetime.now(BRT).isoformat()

        await sb.upsert_contact_memory(org_id, phone, merged, chatwoot_contact_id)

        old_status = existing.get("qualification_status", "new") if existing else "new"
        new_status = merged.get("qualification_status", "cold")
        new_interests = [i for i in (merged.get("interests") or [])
                         if i not in (existing.get("interests") or [] if existing else [])]

        if old_status != new_status:
            log.info(
                "[MEMORY:SAVE] Memória salva para %s (status: %s → %s)",
                contact_phone, old_status, new_status,
            )
        elif new_interests:
            log.info(
                "[MEMORY:UPDATE] Memória atualizada para %s (novo interesse: %s)",
                contact_phone, ", ".join(new_interests),
            )
        else:
            log.info("[MEMORY:SAVE] Memória salva para %s", contact_phone)

    except Exception as exc:
        log.error("[MEMORY:SAVE] Error saving memory for %s: %s", contact_phone, exc, exc_info=True)


def _parse_json_response(text: str) -> Optional[dict]:
    """Extract JSON from a response that may have markdown fences or extra text."""
    # 1) Direct parse
    try:
        return json.loads(text)
    except Exception:
        pass
    # 2) Strip markdown fences
    cleaned = re.sub(r"```json\s*", "", text)
    cleaned = re.sub(r"```\s*", "", cleaned).strip()
    try:
        return json.loads(cleaned)
    except Exception:
        pass
    # 3) Find first { ... last }
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        try:
            return json.loads(text[start : end + 1])
        except Exception:
            pass
    return None


async def _extract_memory(history: list[dict]) -> Optional[dict]:
    """Use Claude Haiku to extract structured info from conversation history."""
    from app.integrations.claude_client import generate_extraction

    # Build conversation text with clear role separation
    lines = []
    for msg in history[-30:]:  # Last 30 messages max
        role = "LEAD" if msg.get("role") == "user" else "AURORA (IA)"
        lines.append(f"[{role}]: {msg.get('content', '')}")
    conversation_text = "\n".join(lines)

    prompt = (
        "Analise esta conversa entre um lead e a IA (Aurora). "
        "Responda APENAS em JSON válido, sem markdown:\n"
        "{\n"
        '  "contact_name": "nome do lead ou null",\n'
        '  "contact_company": "empresa/negócio do lead ou null",\n'
        '  "contact_email": "email do lead ou null",\n'
        '  "summary": "Resumo em 2-3 frases do que foi discutido",\n'
        '  "interests": ["max 5 interesses REAIS do lead"],\n'
        '  "qualification_status": "cold|warm|hot",\n'
        '  "key_info": {}\n'
        "}\n\n"
        "REGRAS CRÍTICAS PARA O CAMPO interests:\n"
        "- Extraia interesses SOMENTE do que o LEAD disse (linhas [LEAD]).\n"
        "- NUNCA inclua produtos/serviços que a AURORA (IA) mencionou ou ofereceu.\n"
        "- Interesses são: o negócio do lead, o que ele busca, a necessidade/dor dele.\n"
        "- Máximo 5 interesses, apenas os mais relevantes.\n"
        "- Se o lead disse 'tenho uma padaria e quero vender mais' → interests: ['padaria', 'aumento de vendas']\n"
        "- Se a IA disse 'temos CRM, landing pages, disparos' → NÃO incluir esses termos.\n\n"
        "Conversa:\n"
        f"{conversation_text}"
    )

    try:
        raw, _ = await generate_extraction(prompt)
        data = _parse_json_response(raw)
        if data is None:
            log.warning(
                "[MEMORY:EXTRACT] Could not parse JSON from Haiku response: %s",
                raw[:200],
            )
        return data
    except Exception as exc:
        log.error("[MEMORY:EXTRACT] Haiku extraction failed: %s", exc)
        return None


def _merge_memory(existing: Optional[dict], new_data: dict) -> dict:
    """Merge new extracted data with existing memory.

    Rules:
    - New non-null values override old ones
    - Interests are merged (union, no duplicates)
    - Summary is replaced with the newer one
    """
    if not existing:
        return {
            "contact_name": new_data.get("contact_name"),
            "contact_company": new_data.get("contact_company"),
            "contact_email": new_data.get("contact_email"),
            "summary": new_data.get("summary"),
            "interests": new_data.get("interests") or [],
            "qualification_status": new_data.get("qualification_status", "cold"),
            "metadata": new_data.get("key_info") or {},
        }

    merged = dict(existing)

    # Update fields if new data has non-null values
    for field in ("contact_name", "contact_company", "contact_email"):
        new_val = new_data.get(field)
        if new_val:
            merged[field] = new_val

    # Summary: always take the newer one (more context)
    new_summary = new_data.get("summary")
    if new_summary:
        merged["summary"] = new_summary

    # Interests: merge without duplicates, cap at 5 (newest first)
    old_interests = list(merged.get("interests") or [])
    new_interests = list(new_data.get("interests") or [])
    # New interests take priority, then old, deduplicated
    seen = set()
    combined = []
    for i in new_interests + old_interests:
        low = i.lower().strip()
        if low and low not in seen:
            seen.add(low)
            combined.append(i.strip())
    merged["interests"] = combined[:5]

    # Qualification: take new if it's "higher"
    status_rank = {"cold": 0, "warm": 1, "hot": 2, "converted": 3, "lost": -1}
    old_rank = status_rank.get(merged.get("qualification_status", "cold"), 0)
    new_rank = status_rank.get(new_data.get("qualification_status", "cold"), 0)
    if new_rank > old_rank:
        merged["qualification_status"] = new_data["qualification_status"]

    # Merge key_info metadata
    old_meta = merged.get("metadata") or {}
    new_meta = new_data.get("key_info") or {}
    if isinstance(old_meta, str):
        try:
            old_meta = json.loads(old_meta)
        except Exception:
            old_meta = {}
    if new_meta:
        old_meta.update(new_meta)
        merged["metadata"] = old_meta

    return merged
