"""Conversation resolver — auto-resolve Chatwoot conversations when appropriate."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import httpx

from app.config import settings
from app.integrations import supabase_client as sb
from app.utils.logger import get_logger

log = get_logger("resolve")

BRT = timezone(timedelta(hours=-3))

REASONS = {
    "reuniao_agendada": "Reuniao agendada com sucesso. Lead pode enviar nova mensagem a qualquer momento.",
    "handoff_frustrado": "Lead demonstrou frustracao — handoff e resolucao para limpar fila.",
    "lead_desistiu": "Lead informou que nao tem interesse. Conversa encerrada.",
    "timeout_sem_resposta": "Lead nao respondeu apos reativacao (7d + 3 dias). Conversa arquivada.",
    "finalizado": "Atendimento finalizado pela {agent_name}.",
}


async def _get_chatwoot_config(org_id: str) -> tuple[str, int, dict]:
    """Get Chatwoot base_url, account_id, and headers for an org."""
    conn = await sb.get_chatwoot_connection_cached(org_id)

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
    return base_url, account_id, headers


async def resolve_conversation(
    org_id: str,
    conversation_id: str,
    reason: str,
) -> bool:
    """Resolve a Chatwoot conversation with a private note explaining why.

    Args:
        org_id: Organization ID.
        conversation_id: Chatwoot conversation ID.
        reason: Reason key (from REASONS dict) or custom text.

    Returns True if resolved successfully.
    """
    try:
        base_url, account_id, headers = await _get_chatwoot_config(org_id)

        # Fetch dynamic agent name
        agent_name = "Ana"
        try:
            active = await sb.get_active_agents(org_id)
            if active:
                agent_name = active[0].get("agent_name") or "Ana"
        except Exception:
            pass

        reason_text = REASONS.get(reason, reason)
        # Apply agent_name placeholder if present
        if "{agent_name}" in reason_text:
            reason_text = reason_text.format(agent_name=agent_name)

        note = (
            f"Conversa resolvida automaticamente pela {agent_name}.\n"
            f"Motivo: {reason_text}"
        )

        async with httpx.AsyncClient(timeout=10) as client:
            # Private note before resolving
            msg_url = (
                f"{base_url}/api/v1/accounts/{account_id}"
                f"/conversations/{conversation_id}/messages"
            )
            await client.post(
                msg_url,
                json={
                    "content": note,
                    "message_type": "outgoing",
                    "private": True,
                },
                headers=headers,
            )

            # Toggle status to resolved
            status_url = (
                f"{base_url}/api/v1/accounts/{account_id}"
                f"/conversations/{conversation_id}/toggle_status"
            )
            resp = await client.post(
                status_url,
                json={"status": "resolved"},
                headers=headers,
            )
            resp.raise_for_status()

        log.info(
            "[RESOLVE] Conversation %s resolved — reason: %s (org=%s)",
            conversation_id, reason, org_id,
        )
        return True

    except Exception as exc:
        log.error(
            "[RESOLVE] Failed to resolve conversation %s: %s",
            conversation_id, exc,
        )
        return False


async def _delayed_resolve(
    org_id: str,
    conversation_id: str,
    delay_minutes: int,
    reason: str,
) -> None:
    """Background task: wait then resolve if lead hasn't sent new messages."""
    try:
        log.info(
            "[RESOLVE] Scheduled resolution in %d min — conv=%s reason=%s",
            delay_minutes, conversation_id, reason,
        )
        await asyncio.sleep(delay_minutes * 60)

        # Check if lead sent a message during the delay
        check_after = (
            datetime.now(BRT) - timedelta(minutes=delay_minutes)
        ).isoformat()
        try:
            latest = await sb.get_latest_user_message_time(
                int(conversation_id), check_after,
            )
            if latest:
                log.info(
                    "[RESOLVE] Skipping — lead responded during delay (conv=%s)",
                    conversation_id,
                )
                return
        except (ValueError, TypeError):
            pass

        await resolve_conversation(org_id, conversation_id, reason)

    except asyncio.CancelledError:
        log.info("[RESOLVE] Scheduled resolution cancelled (conv=%s)", conversation_id)
    except Exception as exc:
        log.error(
            "[RESOLVE] Error in delayed resolution (conv=%s): %s",
            conversation_id, exc,
        )


def schedule_resolve(
    org_id: str,
    conversation_id: str,
    delay_minutes: int,
    reason: str,
) -> None:
    """Schedule a conversation resolution with a delay (fire-and-forget).

    For short delays (< 60 min), uses asyncio task with sleep.
    For persistent long delays, use schedule_resolve_via_queue instead.
    """
    asyncio.create_task(
        _delayed_resolve(org_id, conversation_id, delay_minutes, reason)
    )
    log.info(
        "[RESOLVE] Resolution queued: conv=%s in %d min (reason=%s)",
        conversation_id, delay_minutes, reason,
    )


async def schedule_resolve_via_queue(
    org_id: str,
    conversation_id: int,
    contact_phone: str,
    delay_minutes: int,
    reason: str = "timeout_sem_resposta",
) -> None:
    """Schedule resolution via followup_queue (survives restarts).

    Inserts a special '__resolve_timeout' entry that the worker
    interprets as a resolve action instead of a template send.
    """
    scheduled_at = (
        datetime.now(BRT) + timedelta(minutes=delay_minutes)
    ).isoformat()

    await sb.insert_followup(
        org_id=org_id,
        conversation_id=conversation_id,
        contact_phone=contact_phone,
        contact_name="",
        template_name="__resolve_timeout",
        template_variables=[],
        scheduled_at=scheduled_at,
        metadata={"reason": reason},
    )
    log.info(
        "[RESOLVE] Timeout queued via followup_queue: conv=%s in %d min",
        conversation_id, delay_minutes,
    )
