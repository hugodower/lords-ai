"""Schedule and cancel follow-up messages in the queue."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from app.integrations import supabase_client as sb
from app.utils.logger import get_logger

log = get_logger("followup:scheduler")

BRT = timezone(timedelta(hours=-3))


# ── Public API ──────────────────────────────────────────────────────


async def cancel_pending_followups(conversation_id: int, reason: str = "lead respondeu") -> int:
    """Cancel ALL pending follow-ups for a conversation (lead responded)."""
    count = await sb.cancel_followups_for_conversation(conversation_id)
    if count > 0:
        log.info(
            "[FOLLOWUP:CANCEL] Cancelados %d follow-ups pendentes para conv %s (%s)",
            count, conversation_id, reason,
        )
    return count


async def schedule_followups_after_reply(
    org_id: str,
    conversation_id: int,
    contact_phone: str,
    contact_name: str,
    action: str,
    lead_temperature: str = "cold",
    skill_used: str = "",
) -> None:
    """Schedule follow-up messages after Aurora replies and waits for lead response.

    Called AFTER Aurora sends a reply. If the lead doesn't respond,
    these follow-ups will fire at the scheduled times.
    """
    # Don't schedule if conversation ended
    if action in ("handoff", "blocked"):
        log.info(
            "[FOLLOWUP:SCHEDULE] Skipping — action=%s for conv %s",
            action, conversation_id,
        )
        return

    # Load org follow-up config
    config = await sb.get_followup_config(org_id)
    if not config or not config.get("followup_enabled", True):
        log.info("[FOLLOWUP:SCHEDULE] Follow-ups disabled for org %s", org_id)
        return

    now = datetime.now(BRT)

    # followup_24h → 24h from now
    if config.get("followup_24h_enabled", True):
        await _schedule_if_not_exists(
            org_id=org_id,
            conversation_id=conversation_id,
            contact_phone=contact_phone,
            contact_name=contact_name,
            template_name="followup_24h",
            variables=[contact_name or ""],
            scheduled_at=now + timedelta(hours=24),
        )

    # followup_48h_agendar → 48h from now, ONLY if lead is qualified (warm/hot)
    if config.get("followup_48h_enabled", True) and lead_temperature in ("warm", "hot"):
        await _schedule_if_not_exists(
            org_id=org_id,
            conversation_id=conversation_id,
            contact_phone=contact_phone,
            contact_name=contact_name,
            template_name="followup_48h_agendar",
            variables=[contact_name or ""],
            scheduled_at=now + timedelta(hours=48),
        )

    # reativacao_7d → 7 days from now
    if config.get("reativacao_7d_enabled", True):
        await _schedule_if_not_exists(
            org_id=org_id,
            conversation_id=conversation_id,
            contact_phone=contact_phone,
            contact_name=contact_name,
            template_name="reativacao_7d",
            variables=[contact_name or ""],
            scheduled_at=now + timedelta(days=7),
        )


async def schedule_booking_followups(
    org_id: str,
    conversation_id: int,
    contact_phone: str,
    contact_name: str,
    meeting_date: str,
    meeting_time: str,
) -> None:
    """Schedule confirmation + reminder after a meeting is booked.

    Args:
        meeting_date: date string like "Quarta, 26/03" (display format)
        meeting_time: time string like "09:00"
    """
    config = await sb.get_followup_config(org_id)
    if not config:
        config = {}

    now = datetime.now(BRT)

    # confirmacao_agendamento → immediate
    if config.get("confirmacao_enabled", True):
        await _schedule_if_not_exists(
            org_id=org_id,
            conversation_id=conversation_id,
            contact_phone=contact_phone,
            contact_name=contact_name,
            template_name="confirmacao_agendamento",
            variables=[contact_name or "", meeting_date, meeting_time],
            scheduled_at=now + timedelta(seconds=10),
            metadata={"meeting_date": meeting_date, "meeting_time": meeting_time},
        )

    # lembrete_reuniao → 1h before meeting
    if config.get("lembrete_enabled", True):
        # Parse the meeting datetime to schedule the reminder
        meeting_dt = _parse_meeting_datetime(meeting_date, meeting_time)
        if meeting_dt:
            reminder_at = meeting_dt - timedelta(hours=1)
            # Only schedule if reminder time is in the future
            if reminder_at > now:
                await _schedule_if_not_exists(
                    org_id=org_id,
                    conversation_id=conversation_id,
                    contact_phone=contact_phone,
                    contact_name=contact_name,
                    template_name="lembrete_reuniao",
                    variables=[contact_name or "", meeting_time],
                    scheduled_at=reminder_at,
                    metadata={"meeting_date": meeting_date, "meeting_time": meeting_time},
                )
            else:
                log.warning(
                    "[FOLLOWUP:SCHEDULE] Reminder time %s is in the past, skipping",
                    reminder_at.isoformat(),
                )


# ── Internals ───────────────────────────────────────────────────────


async def _schedule_if_not_exists(
    org_id: str,
    conversation_id: int,
    contact_phone: str,
    contact_name: str,
    template_name: str,
    variables: list[str],
    scheduled_at: datetime,
    metadata: Optional[dict] = None,
) -> bool:
    """Schedule a follow-up only if one doesn't already exist pending."""
    exists = await sb.followup_exists_pending(conversation_id, template_name)
    if exists:
        log.info(
            "[FOLLOWUP:SCHEDULE] Skipping %s for conv %s — already pending",
            template_name, conversation_id,
        )
        return False

    await sb.insert_followup(
        org_id=org_id,
        conversation_id=conversation_id,
        contact_phone=contact_phone,
        contact_name=contact_name,
        template_name=template_name,
        template_variables=variables,
        scheduled_at=scheduled_at.isoformat(),
        metadata=metadata or {},
    )

    log.info(
        "[FOLLOWUP:SCHEDULE] Agendado %s para conv %s em %s",
        template_name, conversation_id, scheduled_at.strftime("%Y-%m-%d %H:%M BRT"),
    )
    return True


def _parse_meeting_datetime(meeting_date: str, meeting_time: str) -> Optional[datetime]:
    """Try to parse a meeting datetime from display format strings.

    The meeting_date comes from the scheduling confirmation, like "Quarta, 26/03"
    and meeting_time is "09:00". We need the actual datetime to schedule the reminder.
    """
    try:
        # Extract DD/MM from the display date
        # Format: "Quarta, 26/03" or just "26/03" or "26/03/2026"
        import re

        match = re.search(r"(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?", meeting_date)
        if not match:
            log.warning("[FOLLOWUP] Could not parse meeting date: %s", meeting_date)
            return None

        day = int(match.group(1))
        month = int(match.group(2))
        year_str = match.group(3)

        now = datetime.now(BRT)
        if year_str:
            year = int(year_str)
            if year < 100:
                year += 2000
        else:
            year = now.year
            # If the date would be in the past, assume next year
            test_dt = datetime(year, month, day, tzinfo=BRT)
            if test_dt.date() < now.date():
                year += 1

        hour, minute = meeting_time.split(":")
        return datetime(year, month, day, int(hour), int(minute), tzinfo=BRT)

    except Exception as exc:
        log.warning(
            "[FOLLOWUP] Failed to parse meeting datetime: date=%s time=%s error=%s",
            meeting_date, meeting_time, exc,
        )
        return None
