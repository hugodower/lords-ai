from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

from app.integrations import supabase_client as sb
from app.integrations.google_calendar import GoogleCalendarClient
from app.utils.logger import get_logger

log = get_logger("skill:schedule")


async def get_scheduling_info(org_id: str) -> dict:
    """Get scheduling configuration for the org."""
    config = await sb.get_scheduling_config(org_id)
    if not config:
        return {"type": "collect_preference", "configured": False}

    return {
        "type": config.get("scheduling_type", "collect_preference"),
        "configured": True,
        "external_link": config.get("external_link"),
        "calendar_id": config.get("google_calendar_id"),
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
    oauth_token = config.get("google_oauth_token")
    if not oauth_token:
        log.warning("[GCAL] No google_oauth_token in scheduling config for org %s", org_id)
        return None
    if not isinstance(oauth_token, dict):
        log.warning(
            "[GCAL] google_oauth_token is %s (expected dict) for org %s",
            type(oauth_token).__name__, org_id,
        )
        return None
    log.info("[GCAL] Client built for org %s (token type=%s)", org_id, type(oauth_token).__name__)
    return GoogleCalendarClient(org_id=org_id, token_data=oauth_token)


async def get_available_slots(org_id: str, days_ahead: int = 7) -> list[dict]:
    """Get available calendar slots."""
    config = await sb.get_scheduling_config(org_id)
    if not config or config.get("scheduling_type") != "google_calendar":
        return []

    cal_client = _build_gcal_client(config, org_id)
    if not cal_client:
        return []

    calendar_id = config.get("google_calendar_id") or "primary"
    min_advance = config.get("min_advance_hours") or 2
    now = datetime.utcnow()
    start = now + timedelta(hours=min_advance)
    end = now + timedelta(days=min(days_ahead, config.get("max_advance_days") or 30))

    return await cal_client.get_free_slots(
        calendar_id=calendar_id,
        date_start=start,
        date_end=end,
        duration_minutes=config.get("slot_duration_minutes") or 60,
        buffer_minutes=config.get("buffer_minutes") or 15,
        available_start_time=config.get("available_start_time") or "08:00",
        available_end_time=config.get("available_end_time") or "17:00",
    )


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
    config = await sb.get_scheduling_config(org_id)
    if not config or config.get("scheduling_type") != "google_calendar":
        log.warning("Google Calendar not configured for org %s", org_id)
        return None

    cal_client = _build_gcal_client(config, org_id)
    if not cal_client:
        log.error("[BOOKING] Could not build Google Calendar client for org %s", org_id)
        return None

    calendar_id = config.get("google_calendar_id", "primary")
    log.info("[BOOKING] Creating event on calendar '%s' for org %s", calendar_id, org_id)
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
        log.info("Booking created for org %s: %s", org_id, event.get("id"))
    return event


async def execute_scheduling(
    org_id: str,
    contact_name: str,
    contact_phone: str,
    contact_email: Optional[str] = None,
    requested_date: Optional[str] = None,
    requested_time: Optional[str] = None,
) -> dict:
    """Execute the full scheduling flow: create event + build confirmation."""
    log.info(
        "[SCHEDULE] execute_scheduling called: org=%s contact=%s date=%s time=%s",
        org_id, contact_name, requested_date, requested_time,
    )
    config = await sb.get_scheduling_config(org_id)

    if not config:
        log.error("[SCHEDULE] No scheduling config found for org %s", org_id)
        return {"success": False, "error": "Scheduling config not found"}
    if config.get("scheduling_type") != "google_calendar":
        log.error(
            "[SCHEDULE] scheduling_type='%s' (expected 'google_calendar') for org %s",
            config.get("scheduling_type"), org_id,
        )
        return {"success": False, "error": f"scheduling_type is '{config.get('scheduling_type')}', not 'google_calendar'"}

    if not requested_date or not requested_time:
        return {"success": False, "error": "Date and time required"}

    try:
        duration = config.get("slot_duration_minutes", 60)
        start = datetime.fromisoformat(f"{requested_date}T{requested_time}:00")
        end = start + timedelta(minutes=duration)

        # Get company info for the event
        company = await sb.get_company_info(org_id)
        company_name = company.get("company_name", "") if company else ""
        address = company.get("address", "") if company else ""

        event = await create_booking(
            org_id=org_id,
            summary=f"Atendimento - {contact_name} | {company_name}",
            description=f"Lead: {contact_name}\nTelefone: {contact_phone}\nAgendado via IA (SDR)",
            start=start,
            end=end,
            attendee_email=contact_email,
            attendee_phone=contact_phone,
        )

        if not event:
            return {"success": False, "error": "Failed to create event"}

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
            .replace("{nome}", contact_name)
        )

        log.info("[SCHEDULE] Event created for %s at %s", contact_name, start)

        return {
            "success": True,
            "event_id": event.get("id"),
            "confirmation_message": confirm_msg,
            "start": start.isoformat(),
            "end": end.isoformat(),
        }

    except Exception as exc:
        log.error("[SCHEDULE] Error creating event: %s", exc)
        return {"success": False, "error": str(exc)}
