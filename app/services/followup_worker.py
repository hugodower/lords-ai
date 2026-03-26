"""Background worker that processes the follow-up queue every 60 seconds."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

from app.integrations import supabase_client as sb
from app.services.whatsapp_sender import send_template
from app.skills.business_hours import is_within_business_hours
from app.utils.logger import get_logger

log = get_logger("followup:worker")

BRT = timezone(timedelta(hours=-3))

POLL_INTERVAL_SECONDS = 60

# Global flag for graceful shutdown
_shutdown = False


async def start_worker() -> None:
    """Main worker loop — polls followup_queue every 60s."""
    global _shutdown
    _shutdown = False

    log.info("[FOLLOWUP:WORKER] Worker started — polling every %ds", POLL_INTERVAL_SECONDS)

    while not _shutdown:
        try:
            await _process_pending()
        except Exception as exc:
            log.error("[FOLLOWUP:WORKER] Error in processing cycle: %s", exc, exc_info=True)

        await asyncio.sleep(POLL_INTERVAL_SECONDS)

    log.info("[FOLLOWUP:WORKER] Worker stopped")


def stop_worker() -> None:
    """Signal the worker to stop after current cycle."""
    global _shutdown
    _shutdown = True
    log.info("[FOLLOWUP:WORKER] Shutdown requested")


async def _process_pending() -> None:
    """Fetch and process all due follow-ups."""
    now = datetime.now(BRT).isoformat()
    pending = await sb.get_pending_followups(now)

    if not pending:
        return

    log.info("[FOLLOWUP:WORKER] Found %d pending follow-ups to process", len(pending))

    for item in pending:
        await _process_single(item)


async def _process_single(item: dict) -> None:
    """Process one follow-up item from the queue."""
    fid = item["id"]
    org_id = item["organization_id"]
    conv_id = item["conversation_id"]
    template_name = item["template_name"]
    contact_phone = item["contact_phone"]
    contact_name = item.get("contact_name", "")

    log.info(
        "[FOLLOWUP:SEND] Processing %s — conv=%s template=%s phone=%s",
        fid, conv_id, template_name, contact_phone,
    )

    # Handle resolve timeout (special entry, not a real template)
    if template_name == "__resolve_timeout":
        if await _lead_responded_since(conv_id, item["created_at"]):
            await sb.update_followup_status(fid, "cancelled")
            log.info("[RESOLVE] Timeout cancelled — lead responded (conv=%s)", conv_id)
            return

        from app.services.conversation_resolver import resolve_conversation
        from app.services.pipeline_manager import update_stage

        await resolve_conversation(org_id, str(conv_id), "timeout_sem_resposta")
        await update_stage(org_id, contact_phone, str(conv_id), "perdeu", contact_name)
        await sb.update_followup_status(fid, "sent", sent_at=datetime.now(BRT).isoformat())
        log.info("[RESOLVE] Timeout resolution executed for conv=%s", conv_id)
        return

    # Safety check: verify lead hasn't responded since this was scheduled
    if await _lead_responded_since(conv_id, item["created_at"]):
        await sb.update_followup_status(fid, "cancelled")
        log.info(
            "[FOLLOWUP:CANCEL] Follow-up %s cancelled — lead responded since scheduling (conv=%s)",
            fid, conv_id,
        )
        return

    # Check business hours — don't send outside hours
    # (for confirmacao and lembrete, skip this check — they're time-sensitive)
    if template_name not in ("confirmacao_agendamento", "lembrete_reuniao"):
        if not await is_within_business_hours(org_id):
            # Reschedule to next business hours window (try again in 1h)
            log.info(
                "[FOLLOWUP:SEND] Outside business hours for org %s — will retry next cycle",
                org_id,
            )
            return  # Leave as pending, worker will retry next cycle

    # Get WhatsApp credentials for this org
    creds = await sb.get_whatsapp_credentials(org_id)
    if not creds:
        await sb.update_followup_status(fid, "failed", error="No WhatsApp credentials")
        log.error(
            "[FOLLOWUP:FAIL] No WhatsApp credentials for org %s — follow-up %s failed",
            org_id, fid,
        )
        return

    phone_number_id = creds["phone_number_id"]
    access_token = creds["access_token"]

    # Build variables from stored data
    variables = item.get("template_variables") or []
    if isinstance(variables, str):
        import json
        try:
            variables = json.loads(variables)
        except Exception:
            variables = []

    # Send the template
    result = await send_template(
        phone_number_id=phone_number_id,
        access_token=access_token,
        to_phone=contact_phone,
        template_name=template_name,
        variables=variables,
    )

    if result.get("success"):
        now_str = datetime.now(BRT).isoformat()
        await sb.update_followup_status(fid, "sent", sent_at=now_str)
        log.info(
            "[FOLLOWUP:SUCCESS] Template %s enviado para conv %s (%s) — wamid=%s",
            template_name, conv_id, contact_phone, result.get("wamid"),
        )
        # After reativacao_7d, schedule timeout resolve (3 days)
        if template_name == "reativacao_7d":
            try:
                from app.services.conversation_resolver import schedule_resolve_via_queue
                await schedule_resolve_via_queue(
                    org_id=org_id,
                    conversation_id=conv_id,
                    contact_phone=contact_phone,
                    delay_minutes=3 * 24 * 60,
                    reason="timeout_sem_resposta",
                )
            except Exception as resolve_err:
                log.warning("[RESOLVE] Failed to queue timeout resolve: %s", resolve_err)
    else:
        error = result.get("error", "unknown")
        await sb.update_followup_status(fid, "failed", error=error)
        log.error(
            "[FOLLOWUP:FAIL] Erro ao enviar %s para conv %s: %s",
            template_name, conv_id, error,
        )


async def _lead_responded_since(conversation_id: int, created_at: str) -> bool:
    """Check if the lead sent a message after the follow-up was created."""
    try:
        latest = await sb.get_latest_user_message_time(conversation_id, created_at)
        return latest is not None
    except Exception as exc:
        log.warning(
            "[FOLLOWUP:WORKER] Error checking lead response for conv %s: %s",
            conversation_id, exc,
        )
        # On error, don't send (safety)
        return True
