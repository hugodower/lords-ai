from __future__ import annotations

from datetime import datetime, timezone, timedelta

from app.integrations import supabase_client as sb
from app.utils.logger import get_logger

log = get_logger("skill:business_hours")

# Brazil timezone (UTC-3)
BRT = timezone(timedelta(hours=-3))


async def is_within_business_hours(org_id: str) -> bool:
    """Check if current time is within business hours for this org."""
    now = datetime.now(BRT)
    day = now.weekday()  # Monday=0, Sunday=6
    # Convert to our schema: 0=domingo, 1=segunda, ..., 6=sábado
    schema_day = (day + 1) % 7

    hours = await sb.get_business_hours(org_id)
    if not hours:
        # No business hours configured — assume always open
        return True

    today = next((h for h in hours if h["day_of_week"] == schema_day), None)
    if not today or not today.get("is_open"):
        log.info("Org %s is closed today (day=%d)", org_id, schema_day)
        return False

    open_time = today.get("open_time")
    close_time = today.get("close_time")
    if not open_time or not close_time:
        return True

    # Parse HH:MM:SS or HH:MM
    current_time = now.strftime("%H:%M:%S")
    if current_time < open_time or current_time > close_time:
        log.info(
            "Org %s outside hours: %s not in [%s, %s]",
            org_id, current_time, open_time, close_time,
        )
        return False

    return True


async def get_after_hours_response(org_id: str) -> tuple[str, str]:
    """Get the after-hours message and behavior.

    Returns (message, behavior) where behavior is one of:
    - 'reply_and_stop': send message and stop
    - 'reply_and_qualify': send message but continue qualifying
    - 'silent': don't send anything
    """
    config = await sb.get_business_hours_config(org_id)
    if not config:
        return (
            "Olá! No momento estamos fechados. Retornamos no próximo dia útil!",
            "reply_and_stop",
        )
    return (
        config.get("after_hours_message", "Olá! No momento estamos fechados."),
        config.get("after_hours_behavior", "reply_and_stop"),
    )
