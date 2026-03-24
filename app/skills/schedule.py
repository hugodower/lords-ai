from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

from app.integrations import supabase_client as sb
from app.integrations.google_calendar import GoogleCalendarClient
from app.utils.logger import get_logger

log = get_logger("skill:schedule")


async def get_scheduling_info(org_id: str) -> dict:
    """Get scheduling configuration for the org."""
    log.info("[SCHED] get_scheduling_info called — org=%s", org_id)
    config = await sb.get_scheduling_config(org_id)
    if not config:
        log.warning("[SCHED] No scheduling_config found for org %s — returning defaults", org_id)
        return {"type": "collect_preference", "configured": False}

    stype = config.get("scheduling_type", "collect_preference")
    has_token = bool(config.get("google_oauth_token"))
    cal_id = config.get("google_calendar_id")
    log.info(
        "[SCHED] scheduling_config loaded — org=%s, type=%s, calendar_id=%s, has_oauth_token=%s",
        org_id, stype, cal_id, has_token,
    )

    return {
        "type": stype,
        "configured": True,
        "external_link": config.get("external_link"),
        "calendar_id": cal_id,
        "slot_duration": config.get("slot_duration_minutes", 60),
        "buffer_minutes": config.get("buffer_minutes", 15),
        "available_start": config.get("available_start_time", "08:00"),
        "available_end": config.get("available_end_time", "17:00"),
        "min_advance_hours": config.get("min_advance_hours", 2),
        "max_advance_days": config.get("max_advance_days", 30),
        "booking_message": config.get(
            "confirm_message",
            config.get("booking_message", "Pronto! Agendei para {data} as {hora}. Qualquer duvida e so chamar!"),
        ),
    }


def _build_gcal_client(config: dict, org_id: str) -> Optional[GoogleCalendarClient]:
    """Build a GoogleCalendarClient from scheduling config, if connected."""
    log.info("[SCHED:BUILD] _build_gcal_client called for org %s", org_id)
    oauth_token = config.get("google_oauth_token")
    if not oauth_token:
        log.error("[SCHED:BUILD] No google_oauth_token in scheduling config for org %s — CANNOT build client", org_id)
        return None
    if not isinstance(oauth_token, dict):
        log.error(
            "[SCHED:BUILD] google_oauth_token is %s (expected dict) for org %s — value preview: %s",
            type(oauth_token).__name__, org_id, str(oauth_token)[:100],
        )
        return None

    token_keys = list(oauth_token.keys())
    has_access = bool(oauth_token.get("access_token"))
    has_refresh = bool(oauth_token.get("refresh_token"))
    expiry = oauth_token.get("expiry_date", 0)
    log.info(
        "[SCHED:BUILD] Token data — keys=%s, has_access=%s, has_refresh=%s, expiry_date=%s",
        token_keys, has_access, has_refresh, expiry,
    )
    return GoogleCalendarClient(org_id=org_id, token_data=oauth_token)


async def get_available_slots(org_id: str, days_ahead: int = 7) -> list[dict]:
    """Get available calendar slots."""
    log.info("[SCHED:SLOTS] get_available_slots — org=%s, days_ahead=%d", org_id, days_ahead)

    config = await sb.get_scheduling_config(org_id)
    if not config:
        log.warning("[SCHED:SLOTS] No scheduling_config for org %s", org_id)
        return []
    if config.get("scheduling_type") != "google_calendar":
        log.info("[SCHED:SLOTS] scheduling_type='%s' (not google_calendar) — returning []", config.get("scheduling_type"))
        return []

    cal_client = _build_gcal_client(config, org_id)
    if not cal_client:
        log.error("[SCHED:SLOTS] Failed to build GCal client for org %s", org_id)
        return []

    calendar_id = config.get("google_calendar_id") or "primary"
    min_advance = config.get("min_advance_hours") or 2
    now = datetime.utcnow()
    start = now + timedelta(hours=min_advance)
    end = now + timedelta(days=min(days_ahead, config.get("max_advance_days") or 30))

    log.info(
        "[SCHED:SLOTS] Querying free slots — calendar=%s, start=%s, end=%s",
        calendar_id, start.isoformat(), end.isoformat(),
    )

    slots = await cal_client.get_free_slots(
        calendar_id=calendar_id,
        date_start=start,
        date_end=end,
        duration_minutes=config.get("slot_duration_minutes") or 60,
        buffer_minutes=config.get("buffer_minutes") or 15,
        available_start_time=config.get("available_start_time") or "08:00",
        available_end_time=config.get("available_end_time") or "17:00",
    )
    log.info("[SCHED:SLOTS] Got %d available slots for org %s", len(slots), org_id)
    return slots


async def get_scheduling_context(org_id: str) -> str:
    """Build context string for the Claude prompt about scheduling."""
    config = await sb.get_scheduling_config(org_id)
    if not config:
        return "Agendamento nao configurado. Colete preferencia e passe pro humano."

    stype = config.get("scheduling_type", "disabled")

    if stype == "disabled":
        return "Agendamento desabilitado. Se o lead pedir para agendar, transfira para o humano."

    if stype == "external":
        link = config.get("external_link", "")
        return f"Para agendamento, envie este link pro lead: {link}"

    if stype == "collect_preference":
        return "Pergunte a preferencia de dia e horario do lead e informe que a equipe vai confirmar."

    if stype == "google_calendar":
        slots = await get_available_slots(org_id, days_ahead=7)

        if not slots:
            return (
                "Google Calendar conectado mas sem horarios disponiveis nos proximos 7 dias. "
                "Pergunte ao lead a preferencia e informe que a equipe vai verificar a agenda."
            )

        slots_text = "\n".join(f"  - {s['display']}" for s in slots[:6])
        confirm_msg = config.get(
            "confirm_message",
            config.get("booking_message", "Agendamento confirmado para {data} as {hora}!"),
        )

        return f"""Agendamento via Google Calendar ATIVO.
Horarios disponiveis nos proximos dias:
{slots_text}

Quando o lead escolher um horario, responda com action "schedule" e inclua:
- schedule.requested_date: data no formato YYYY-MM-DD
- schedule.requested_time: horario no formato HH:MM

Mensagem de confirmacao apos agendar: {confirm_msg}

IMPORTANTE: Ofereca no maximo 3 opcoes por mensagem. Se o lead nao gostar, ofereca mais opcoes."""

    return "Agendamento nao configurado. Colete preferencia e passe pro humano."


async def create_booking(
    org_id: str,
    summary: str,
    description: str,
    start: datetime,
    end: datetime,
    attendee_email: Optional[str] = None,
    attendee_phone: Optional[str] = None,
) -> Optional[dict]:
    """Create a calendar booking."""
    log.info(
        "[BOOKING] create_booking called — org=%s, summary='%s', start=%s, end=%s",
        org_id, summary, start.isoformat(), end.isoformat(),
    )

    config = await sb.get_scheduling_config(org_id)
    if not config:
        log.error("[BOOKING] No scheduling_config for org %s", org_id)
        return None
    if config.get("scheduling_type") != "google_calendar":
        log.error("[BOOKING] scheduling_type='%s' (not google_calendar) for org %s", config.get("scheduling_type"), org_id)
        return None

    cal_client = _build_gcal_client(config, org_id)
    if not cal_client:
        log.error("[BOOKING] Could not build Google Calendar client for org %s", org_id)
        return None

    calendar_id = config.get("google_calendar_id", "primary")
    log.info("[BOOKING] Calling GCal create_event — calendar='%s', org=%s", calendar_id, org_id)

    event = await cal_client.create_event(
        calendar_id=calendar_id,
        summary=summary,
        description=description,
        start=start,
        end=end,
        attendee_email=attendee_email,
        attendee_phone=attendee_phone,
    )

    if event:
        log.info("[BOOKING] SUCCESS — event_id=%s, link=%s", event.get("id"), event.get("htmlLink"))
    else:
        log.error("[BOOKING] FAILED — create_event returned None for org %s", org_id)
    return event


async def execute_scheduling(
    org_id: str,
    contact_name: str,
    contact_phone: str,
    contact_email: Optional[str] = None,
    requested_date: Optional[str] = None,
    requested_time: Optional[str] = None,
    attendee_name: Optional[str] = None,
    participant: Optional[str] = None,
    whatsapp_for_reminders: Optional[str] = None,
    interest: Optional[str] = None,
    conversation_id: Optional[str] = None,
) -> dict:
    """Execute the full scheduling flow: create event + build confirmation."""

    # Use attendee_name if provided, fallback to contact_name
    final_name = attendee_name or contact_name
    final_email = contact_email
    final_whatsapp = whatsapp_for_reminders or contact_phone

    log.info(
        "[SCHEDULE] ===== execute_scheduling START =====\n"
        "  org=%s\n  contact=%s (%s)\n  attendee_name=%s\n  email=%s\n"
        "  participant=%s\n  whatsapp=%s\n  interest=%s\n  date=%s  time=%s",
        org_id, contact_name, contact_phone, final_name, final_email,
        participant, final_whatsapp, interest, requested_date, requested_time,
    )

    # Save collected data to Redis session for future reference
    if conversation_id:
        from app.memory.redis_store import set_conversation_metadata
        import json as _json

        sched_data = {
            "attendee_name": final_name,
            "attendee_email": final_email,
            "participant": participant,
            "whatsapp_for_reminders": final_whatsapp,
            "interest": interest,
            "requested_date": requested_date,
            "requested_time": requested_time,
        }
        await set_conversation_metadata(
            conversation_id, "scheduling_data", _json.dumps(sched_data, default=str)
        )
        log.info("[SCHEDULE] Saved scheduling data to Redis session — conv=%s", conversation_id)

    log.info("[SCHEDULE] Step 1: Fetching scheduling_config from Supabase ...")
    config = await sb.get_scheduling_config(org_id)

    if not config:
        log.error("[SCHEDULE] FAIL — No scheduling config found for org %s", org_id)
        return {"success": False, "error": "Scheduling config not found"}

    log.info(
        "[SCHEDULE] Config loaded — type=%s, calendar_id=%s, has_token=%s, slot_duration=%d",
        config.get("scheduling_type"), config.get("google_calendar_id"),
        bool(config.get("google_oauth_token")), config.get("slot_duration_minutes", 60),
    )

    if config.get("scheduling_type") != "google_calendar":
        log.error(
            "[SCHEDULE] FAIL — scheduling_type='%s' (expected 'google_calendar') for org %s",
            config.get("scheduling_type"), org_id,
        )
        return {"success": False, "error": f"scheduling_type is '{config.get('scheduling_type')}', not 'google_calendar'"}

    if not requested_date or not requested_time:
        log.error("[SCHEDULE] FAIL — Date or time missing: date=%s, time=%s", requested_date, requested_time)
        return {"success": False, "error": "Date and time required"}

    try:
        duration = config.get("slot_duration_minutes", 60)
        start = datetime.fromisoformat(f"{requested_date}T{requested_time}:00")

        # Fix wrong year: Claude's training data may cause it to use past years
        now = datetime.utcnow()
        if start.year < now.year:
            log.warning(
                "[SCHEDULE] Wrong year detected: %d (current=%d) — auto-correcting date from %s to %s",
                start.year, now.year, requested_date,
                start.replace(year=now.year).strftime("%Y-%m-%d"),
            )
            start = start.replace(year=now.year)

        # Reject dates in the past
        if start < now:
            log.error(
                "[SCHEDULE] FAIL — Date is in the past: %s (now=%s)",
                start.isoformat(), now.isoformat(),
            )
            return {
                "success": False,
                "error": "past_date",
                "message": f"A data {start.strftime('%d/%m/%Y %H:%M')} já passou. Peça ao lead para escolher outra data.",
            }

        end = start + timedelta(minutes=duration)
        log.info("[SCHEDULE] Step 2: Parsed datetime — start=%s, end=%s, duration=%d min", start, end, duration)

        # Get company info for the event
        log.info("[SCHEDULE] Step 3: Fetching company_info ...")
        company = await sb.get_company_info(org_id)
        company_name = company.get("company_name", "") if company else ""
        address = company.get("address", "") if company else ""
        log.info("[SCHEDULE] Company: name='%s', address='%s'", company_name, address)

        # Build event summary and description using collected data
        summary = f"Reuniao {company_name} x {final_name}"
        participant_info = participant or final_name
        interest_info = interest or "a definir"
        description = (
            f"Reuniao {company_name}\n"
            f"Contato: {final_name}\n"
            f"WhatsApp: {final_whatsapp}\n"
            f"Participante: {participant_info}\n"
            f"Interesse: {interest_info}\n"
            f"Agendado via IA (SDR)"
        )
        log.info("[SCHEDULE] Step 4: Event — summary='%s', attendee_email=%s", summary, final_email)

        log.info("[SCHEDULE] Step 5: Calling create_booking ...")
        event = await create_booking(
            org_id=org_id,
            summary=summary,
            description=description,
            start=start,
            end=end,
            attendee_email=final_email,
            attendee_phone=final_whatsapp,
        )

        if not event:
            log.error("[SCHEDULE] FAIL — create_booking returned None for org %s", org_id)
            return {"success": False, "error": "Failed to create event"}

        log.info("[SCHEDULE] Step 6: Event created — id=%s, building confirmation message ...", event.get("id"))

        # Build confirmation message
        DAYS_PT = ["Segunda", "Terca", "Quarta", "Quinta", "Sexta", "Sabado", "Domingo"]
        day_name = DAYS_PT[start.weekday()]
        confirm_template = config.get(
            "confirm_message",
            config.get("booking_message", "Agendei para {data} as {hora}!"),
        )

        confirm_msg = (
            confirm_template
            .replace("{data}", f"{day_name}, {start.strftime('%d/%m')}")
            .replace("{hora}", start.strftime("%H:%M"))
            .replace("{profissional}", "")
            .replace("{endereco}", address)
            .replace("{nome}", final_name)
        )

        log.info(
            "[SCHEDULE] ===== execute_scheduling SUCCESS =====\n"
            "  event_id=%s\n  confirmation='%s'\n  attendee=%s <%s>\n  start=%s  end=%s",
            event.get("id"), confirm_msg, final_name, final_email,
            start.isoformat(), end.isoformat(),
        )

        return {
            "success": True,
            "event_id": event.get("id"),
            "confirmation_message": confirm_msg,
            "start": start.isoformat(),
            "end": end.isoformat(),
        }

    except Exception as exc:
        log.error("[SCHEDULE] EXCEPTION in execute_scheduling: %s — %s", type(exc).__name__, exc, exc_info=True)
        return {"success": False, "error": str(exc)}
