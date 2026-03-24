"""
Live Google Calendar test — creates a real event to diagnose integration issues.

Run:  python -m tests.test_gcal_live
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import datetime, timedelta

# Ensure project root is in path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import logging

# Force DEBUG for all LORDS-AI loggers
logging.basicConfig(level=logging.DEBUG, stream=sys.stdout,
                    format="%(asctime)s %(levelname)s %(name)s — %(message)s")
for name in ["[LORDS-AI] google_calendar", "[LORDS-AI] supabase", "[LORDS-AI] skill:schedule"]:
    logging.getLogger(name).setLevel(logging.DEBUG)


async def main() -> None:
    # Load env
    from dotenv import load_dotenv
    load_dotenv()

    from app.config import settings

    print("=" * 70)
    print("LORDS-AI  —  Google Calendar Live Diagnostic")
    print("=" * 70)
    print(f"  ORG_ID:               {settings.org_id}")
    print(f"  SUPABASE_URL:         {settings.supabase_url}")
    print(f"  GOOGLE_CLIENT_ID:     {settings.google_client_id[:30]}...")
    print(f"  GOOGLE_CLIENT_SECRET: {'SET' if settings.google_client_secret else 'EMPTY'}")
    print()

    # -- Step 1: Fetch scheduling_config from Supabase ------------------
    print("-" * 70)
    print("[STEP 1] Fetching scheduling_config from Supabase ...")
    from app.integrations.supabase_client import get_scheduling_config
    config = await get_scheduling_config(settings.org_id)

    if not config:
        print("  RESULT: No scheduling_config found for this org.")
        print("  FIX: Insert a row into scheduling_config with scheduling_type='google_calendar'")
        return

    # Pretty-print config (hide full token)
    safe_config = {k: v for k, v in config.items() if k != "google_oauth_token"}
    token = config.get("google_oauth_token")
    if token and isinstance(token, dict):
        safe_config["google_oauth_token"] = {
            "has_access_token": bool(token.get("access_token")),
            "has_refresh_token": bool(token.get("refresh_token")),
            "expiry_date": token.get("expiry_date"),
            "token_type": token.get("token_type"),
            "keys": list(token.keys()),
        }
    elif token:
        safe_config["google_oauth_token"] = f"<type={type(token).__name__}>"
    else:
        safe_config["google_oauth_token"] = None

    print("  RESULT:")
    print(json.dumps(safe_config, indent=4, default=str))
    print()

    stype = config.get("scheduling_type")
    if stype != "google_calendar":
        print(f"  scheduling_type = '{stype}' — not 'google_calendar'.")
        print("  FIX: UPDATE scheduling_config SET scheduling_type = 'google_calendar' ...")
        return

    if not token or not isinstance(token, dict):
        print("  google_oauth_token is missing or not a dict.")
        print("  FIX: Store a valid OAuth token JSON in google_oauth_token column.")
        return

    # -- Step 2: Test token refresh -------------------------------------
    print("-" * 70)
    print("[STEP 2] Testing OAuth token validity / refresh ...")
    from app.integrations.google_calendar import GoogleCalendarClient

    cal_client = GoogleCalendarClient(org_id=settings.org_id, token_data=token)
    access_token = await cal_client._get_access_token()

    if not access_token:
        print("  RESULT: Could not get valid access token.")
        print("  Possible causes:")
        print("    - refresh_token revoked / invalid")
        print("    - GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET mismatch")
        print("    - Google OAuth consent expired (re-authorize needed)")
        return

    print(f"  RESULT: Got access token — {access_token[:25]}...{access_token[-10:]}")
    print()

    # -- Step 3: Test FreeBusy API --------------------------------------
    print("-" * 70)
    print("[STEP 3] Testing FreeBusy API (list busy periods) ...")
    calendar_id = config.get("google_calendar_id") or "primary"
    now = datetime.utcnow()
    slots = await cal_client.get_free_slots(
        calendar_id=calendar_id,
        date_start=now,
        date_end=now + timedelta(days=3),
        duration_minutes=60,
        buffer_minutes=15,
        available_start_time="08:00",
        available_end_time="18:00",
    )
    print(f"  RESULT: {len(slots)} available slots found")
    for s in slots[:5]:
        print(f"    - {s['display']}")
    print()

    # -- Step 4: Create a real test event -------------------------------
    print("-" * 70)
    print("[STEP 4] Creating a REAL test event on Google Calendar ...")

    # Schedule 2 hours from now (rounded to next hour)
    test_start = (now + timedelta(hours=2)).replace(minute=0, second=0, microsecond=0)
    test_end = test_start + timedelta(minutes=30)

    print(f"  Calendar: {calendar_id}")
    print(f"  Start:    {test_start.isoformat()}")
    print(f"  End:      {test_end.isoformat()}")

    event = await cal_client.create_event(
        calendar_id=calendar_id,
        summary="[TESTE] Evento de diagnostico LORDS-AI",
        description="Evento criado automaticamente pelo script de diagnostico.\nPode ser deletado.",
        start=test_start,
        end=test_end,
        attendee_email=None,
        attendee_phone=None,
    )

    if not event:
        print("  RESULT: FAILED — create_event returned None")
        print("  Check the logs above for the exact error.")
        return

    print(f"  RESULT: SUCCESS!")
    print(f"  Event ID:   {event.get('id')}")
    print(f"  HTML Link:  {event.get('htmlLink')}")
    print(f"  Status:     {event.get('status')}")
    print(f"  Created:    {event.get('created')}")
    print()

    # -- Step 5: Clean up — delete the test event ----------------------
    print("-" * 70)
    print("[STEP 5] Cleaning up — deleting test event ...")
    deleted = await cal_client.cancel_event(calendar_id, event["id"])
    print(f"  Deleted: {deleted}")
    print()

    # -- Step 6: Full execute_scheduling flow --------------------------
    print("-" * 70)
    print("[STEP 6] Testing full execute_scheduling() flow ...")

    from app.skills.schedule import execute_scheduling

    # Use tomorrow at 10:00
    tomorrow = (now + timedelta(days=1)).date()
    # Skip weekends
    while tomorrow.weekday() >= 5:
        tomorrow += timedelta(days=1)

    result = await execute_scheduling(
        org_id=settings.org_id,
        contact_name="Teste Diagnostico",
        contact_phone="+5518999999999",
        contact_email=None,
        requested_date=tomorrow.isoformat(),
        requested_time="10:00",
    )

    print(f"  RESULT: {json.dumps(result, indent=4, default=str)}")

    if result.get("success") and result.get("event_id"):
        print("  Cleaning up scheduled test event ...")
        await cal_client.cancel_event(calendar_id, result["event_id"])
        print("  Deleted.")

    print()
    print("=" * 70)
    print("DIAGNOSTIC COMPLETE")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())
