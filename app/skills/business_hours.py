from __future__ import annotations

from datetime import datetime, timezone, timedelta

import holidays
from app.integrations import supabase_client as sb
from app.integrations.supabase_client import get_supabase
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


# Default config caso não encontre no banco
DEFAULT_CALL_CONFIG = {
    'call_window_start_hour': 9,
    'call_window_end_hour': 18,
    'call_blocks_weekends': True,
    'call_country_holidays': 'BR',
}


async def _get_call_config(org_id: str) -> dict:
    """
    Lê config de janela de ligação do banco pra uma org.
    Fallback gracioso pra defaults se não encontrar ou der erro.
    """
    try:
        client = get_supabase()
        result = client.table('agent_configs').select(
            'call_window_start_hour, call_window_end_hour, '
            'call_blocks_weekends, call_country_holidays'
        ).eq('organization_id', org_id).eq('is_active', True).limit(1).execute()

        if result.data and len(result.data) > 0:
            cfg = result.data[0]
            return {
                'call_window_start_hour': cfg.get('call_window_start_hour') or DEFAULT_CALL_CONFIG['call_window_start_hour'],
                'call_window_end_hour': cfg.get('call_window_end_hour') or DEFAULT_CALL_CONFIG['call_window_end_hour'],
                'call_blocks_weekends': cfg.get('call_blocks_weekends') if cfg.get('call_blocks_weekends') is not None else DEFAULT_CALL_CONFIG['call_blocks_weekends'],
                'call_country_holidays': cfg.get('call_country_holidays') or DEFAULT_CALL_CONFIG['call_country_holidays'],
            }
    except Exception as e:
        log.warning(f"[is_valid_call_slot] failed to read agent_configs for org {org_id}: {e}. Using defaults.")

    return DEFAULT_CALL_CONFIG.copy()


async def is_valid_call_slot(dt: datetime, org_id: str) -> tuple[bool, str]:
    """
    Valida se um datetime é slot válido pra agendar ligação.

    Args:
        dt: datetime timezone-aware (preferencialmente America/Sao_Paulo)
        org_id: UUID da org (string) - pra buscar config

    Returns:
        (valido, motivo) - motivo vazio se valido, descrição se invalido

    Examples:
        >>> from datetime import datetime
        >>> dt = datetime(2026, 5, 23, 14, 0, tzinfo=BRT)  # sabado
        >>> await is_valid_call_slot(dt, "31ddcc20-...")
        (False, "Sabado nao e dia util")
    """
    # Garante timezone-aware
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=BRT)

    # Converte pra timezone local pra checks
    dt_local = dt.astimezone(BRT)

    config = await _get_call_config(org_id)

    # Check 1: fim de semana
    weekday = dt_local.weekday()  # 0=segunda, 6=domingo
    if config['call_blocks_weekends'] and weekday >= 5:
        dia_nome = "Sabado" if weekday == 5 else "Domingo"
        return (False, f"{dia_nome} nao e dia util")

    # Check 2: feriado nacional
    country_code = config['call_country_holidays']
    try:
        country_holidays = holidays.country_holidays(country_code, years=dt_local.year)
        if dt_local.date() in country_holidays:
            feriado_nome = country_holidays.get(dt_local.date())
            return (False, f"Feriado nacional: {feriado_nome}")
    except Exception as e:
        log.warning(f"[is_valid_call_slot] failed to check holidays for {country_code}: {e}")
        # Nao bloqueia - segue pros proximos checks

    # Check 3: janela de horario
    hour = dt_local.hour
    start = config['call_window_start_hour']
    end = config['call_window_end_hour']

    if hour < start or hour >= end:
        return (False, f"Fora da janela de atendimento ({start:02d}:00 - {end:02d}:00)")

    return (True, "")
