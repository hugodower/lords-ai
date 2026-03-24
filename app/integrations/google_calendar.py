from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

import httpx

from app.config import settings
from app.utils.logger import get_logger

log = get_logger("google_calendar")

BASE_URL = "https://www.googleapis.com/calendar/v3"
TIMEZONE = "America/Sao_Paulo"


class GoogleCalendarClient:
    """Google Calendar client using httpx with automatic OAuth token refresh."""

    def __init__(self, org_id: str, token_data: dict) -> None:
        self.org_id = org_id
        self._token = token_data
        log.info(
            "[GCAL] Client init — org=%s, token_keys=%s, has_access=%s, has_refresh=%s, expiry=%s",
            org_id,
            list(token_data.keys()) if token_data else "None",
            bool(token_data.get("access_token")) if token_data else False,
            bool(token_data.get("refresh_token")) if token_data else False,
            token_data.get("expiry_date") if token_data else "N/A",
        )

    async def _get_access_token(self) -> Optional[str]:
        """Get valid access token, refreshing if needed."""
        if not self._token:
            log.error("[GCAL:TOKEN] _token is empty/None for org %s", self.org_id)
            return None

        # Check if expired (5 min buffer)
        expiry = self._token.get("expiry_date", 0)
        now_ms = datetime.utcnow().timestamp() * 1000
        remaining_ms = expiry - now_ms
        remaining_min = remaining_ms / 60_000

        log.info(
            "[GCAL:TOKEN] Expiry check — expiry_date=%s, now_ms=%s, remaining=%.1f min, expired=%s",
            expiry, int(now_ms), remaining_min, remaining_ms <= 300_000,
        )

        if expiry > now_ms + 300_000:
            access = self._token.get("access_token")
            log.info(
                "[GCAL:TOKEN] Token still valid (%.1f min left) — access_token=%s...%s",
                remaining_min,
                access[:20] if access else "NONE",
                access[-10:] if access else "",
            )
            return access

        # Need refresh
        log.warning(
            "[GCAL:TOKEN] Token expired or expiring soon (%.1f min left) — initiating refresh for org %s",
            remaining_min, self.org_id,
        )
        refresh_token = self._token.get("refresh_token")
        if not refresh_token:
            log.error("[GCAL:TOKEN] No refresh_token available for org %s — cannot refresh", self.org_id)
            return None

        client_id = settings.google_client_id
        client_secret = settings.google_client_secret
        log.info(
            "[GCAL:TOKEN] Refresh credentials — client_id=%s..., client_secret=%s, refresh_token=%s...%s",
            client_id[:20] if client_id else "EMPTY",
            "SET" if client_secret else "EMPTY",
            refresh_token[:15] if refresh_token else "NONE",
            refresh_token[-5:] if refresh_token else "",
        )
        if not client_id or not client_secret:
            log.error("[GCAL:TOKEN] Missing GOOGLE_CLIENT_ID or GOOGLE_CLIENT_SECRET in .env")
            return None

        try:
            async with httpx.AsyncClient(timeout=15) as client:
                log.info("[GCAL:TOKEN] POST https://oauth2.googleapis.com/token ...")
                resp = await client.post(
                    "https://oauth2.googleapis.com/token",
                    data={
                        "client_id": client_id,
                        "client_secret": client_secret,
                        "refresh_token": refresh_token,
                        "grant_type": "refresh_token",
                    },
                )
                log.info("[GCAL:TOKEN] Refresh response — status=%s", resp.status_code)

                if resp.status_code != 200:
                    log.error(
                        "[GCAL:TOKEN] Token refresh FAILED — status=%s, body=%s",
                        resp.status_code, resp.text,
                    )
                    return None

                new_tokens = resp.json()
                log.info(
                    "[GCAL:TOKEN] Refresh SUCCESS — new keys=%s, expires_in=%s sec",
                    list(new_tokens.keys()), new_tokens.get("expires_in"),
                )

                self._token["access_token"] = new_tokens["access_token"]
                self._token["expiry_date"] = int(
                    datetime.utcnow().timestamp() * 1000
                ) + (new_tokens.get("expires_in", 3600) * 1000)

                # Keep refresh_token if Google returned a new one
                if "refresh_token" in new_tokens:
                    log.info("[GCAL:TOKEN] Google returned new refresh_token — updating")
                    self._token["refresh_token"] = new_tokens["refresh_token"]

                # Persist refreshed token to Supabase
                from app.integrations.supabase_client import update_scheduling_token

                log.info("[GCAL:TOKEN] Persisting refreshed token to Supabase for org %s ...", self.org_id)
                await update_scheduling_token(self.org_id, self._token)
                log.info("[GCAL:TOKEN] Token refreshed and saved — org %s, new expiry=%s", self.org_id, self._token["expiry_date"])
                return self._token["access_token"]
        except Exception as exc:
            log.error("[GCAL:TOKEN] Token refresh EXCEPTION: %s — %s", type(exc).__name__, exc, exc_info=True)
            return None

    async def get_free_slots(
        self,
        calendar_id: str,
        date_start: datetime,
        date_end: datetime,
        duration_minutes: int = 60,
        buffer_minutes: int = 15,
        available_start_time: str = "08:00",
        available_end_time: str = "17:00",
        max_slots: int = 8,
    ) -> list[dict]:
        """Find free time slots using the FreeBusy API."""
        log.info(
            "[GCAL:FREEBUSY] get_free_slots — calendar=%s, range=%s to %s, duration=%d min, hours=%s-%s",
            calendar_id, date_start.isoformat(), date_end.isoformat(),
            duration_minutes, available_start_time, available_end_time,
        )

        access_token = await self._get_access_token()
        if not access_token:
            log.error("[GCAL:FREEBUSY] No access token — aborting free slots query")
            return []

        freebusy_payload = {
            "timeMin": date_start.isoformat() + "Z",
            "timeMax": date_end.isoformat() + "Z",
            "items": [{"id": calendar_id}],
        }

        try:
            async with httpx.AsyncClient(timeout=15) as client:
                log.info("[GCAL:FREEBUSY] POST %s/freeBusy — payload=%s", BASE_URL, freebusy_payload)
                resp = await client.post(
                    f"{BASE_URL}/freeBusy",
                    headers={"Authorization": f"Bearer {access_token}"},
                    json=freebusy_payload,
                )
                log.info("[GCAL:FREEBUSY] Response — status=%s", resp.status_code)
                if resp.status_code != 200:
                    log.error("[GCAL:FREEBUSY] FreeBusy FAILED — status=%s, body=%s", resp.status_code, resp.text)
                    return []

                busy_data = resp.json()
                log.info("[GCAL:FREEBUSY] Response body keys=%s", list(busy_data.keys()))
        except Exception as exc:
            log.error("[GCAL:FREEBUSY] FreeBusy EXCEPTION: %s — %s", type(exc).__name__, exc, exc_info=True)
            return []

        # Collect busy periods
        busy_periods: list[tuple[datetime, datetime]] = []
        for cal_id, cal_data in busy_data.get("calendars", {}).items():
            errors = cal_data.get("errors", [])
            if errors:
                log.error("[GCAL:FREEBUSY] Calendar '%s' errors: %s", cal_id, errors)
            for busy in cal_data.get("busy", []):
                bs = datetime.fromisoformat(busy["start"].replace("Z", "+00:00")).replace(tzinfo=None)
                be = datetime.fromisoformat(busy["end"].replace("Z", "+00:00")).replace(tzinfo=None)
                busy_periods.append((bs, be))

        log.info("[GCAL:FREEBUSY] Found %d busy periods", len(busy_periods))

        # Generate free slots day by day
        DAYS_PT = ["Segunda", "Terca", "Quarta", "Quinta", "Sexta", "Sabado", "Domingo"]
        slots: list[dict] = []
        current_date = date_start.date()
        end_date = date_end.date()

        while current_date <= end_date and len(slots) < max_slots:
            # Skip weekends (Sat=5, Sun=6)
            if current_date.weekday() >= 5:
                current_date += timedelta(days=1)
                continue

            parts = available_start_time.split(":")
            h_start, m_start = int(parts[0]), int(parts[1])
            parts = available_end_time.split(":")
            h_end, m_end = int(parts[0]), int(parts[1])

            slot_start = datetime(
                current_date.year, current_date.month, current_date.day,
                h_start, m_start,
            )
            day_end = datetime(
                current_date.year, current_date.month, current_date.day,
                h_end, m_end,
            )

            while slot_start + timedelta(minutes=duration_minutes) <= day_end and len(slots) < max_slots:
                slot_end = slot_start + timedelta(minutes=duration_minutes)
                is_free = True
                for bs, be in busy_periods:
                    if slot_start < be and slot_end > bs:
                        is_free = False
                        break

                if is_free and slot_start > datetime.utcnow():
                    day_name = DAYS_PT[slot_start.weekday()]
                    display = f"{day_name}, {slot_start.strftime('%d/%m')} as {slot_start.strftime('%H:%M')}"
                    slots.append({
                        "start": slot_start.isoformat(),
                        "end": slot_end.isoformat(),
                        "display": display,
                    })
                slot_start = slot_end + timedelta(minutes=buffer_minutes)

            current_date += timedelta(days=1)

        log.info("[GCAL:FREEBUSY] Returning %d available slots", len(slots))
        return slots

    async def create_event(
        self,
        calendar_id: str,
        summary: str,
        description: str,
        start: datetime,
        end: datetime,
        attendee_email: Optional[str] = None,
        attendee_phone: Optional[str] = None,
    ) -> Optional[dict]:
        """Create a calendar event."""
        log.info(
            "[GCAL:CREATE] create_event called — calendar=%s, summary='%s', start=%s, end=%s, email=%s, phone=%s",
            calendar_id, summary, start.isoformat(), end.isoformat(), attendee_email, attendee_phone,
        )

        access_token = await self._get_access_token()
        if not access_token:
            log.error("[GCAL:CREATE] No access token — cannot create event for org %s", self.org_id)
            return None

        event_body: dict = {
            "summary": summary,
            "description": description + (f"\nTelefone: {attendee_phone}" if attendee_phone else ""),
            "start": {"dateTime": start.isoformat(), "timeZone": TIMEZONE},
            "end": {"dateTime": end.isoformat(), "timeZone": TIMEZONE},
            "reminders": {
                "useDefault": False,
                "overrides": [
                    {"method": "email", "minutes": 1440},
                    {"method": "popup", "minutes": 60},
                ],
            },
        }
        if attendee_email:
            event_body["attendees"] = [{"email": attendee_email}]

        url = f"{BASE_URL}/calendars/{calendar_id}/events"
        log.info("[GCAL:CREATE] POST %s — body_keys=%s", url, list(event_body.keys()))

        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.post(
                    url,
                    headers={
                        "Authorization": f"Bearer {access_token}",
                        "Content-Type": "application/json",
                    },
                    json=event_body,
                )
                log.info("[GCAL:CREATE] Response — status=%s", resp.status_code)

                if resp.status_code not in (200, 201):
                    log.error(
                        "[GCAL:CREATE] Create event FAILED — status=%s, body=%s",
                        resp.status_code, resp.text,
                    )
                    return None

                event = resp.json()
                log.info(
                    "[GCAL:CREATE] Event created SUCCESS — id=%s, htmlLink=%s, org=%s",
                    event.get("id"), event.get("htmlLink"), self.org_id,
                )
                return event
        except Exception as exc:
            log.error("[GCAL:CREATE] Create event EXCEPTION: %s — %s", type(exc).__name__, exc, exc_info=True)
            return None

    async def update_event(
        self,
        calendar_id: str,
        event_id: str,
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
        summary: Optional[str] = None,
    ) -> bool:
        """Update an existing event (reschedule)."""
        access_token = await self._get_access_token()
        if not access_token:
            return False

        update_body: dict = {}
        if start:
            update_body["start"] = {"dateTime": start.isoformat(), "timeZone": TIMEZONE}
        if end:
            update_body["end"] = {"dateTime": end.isoformat(), "timeZone": TIMEZONE}
        if summary:
            update_body["summary"] = summary

        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.patch(
                    f"{BASE_URL}/calendars/{calendar_id}/events/{event_id}",
                    headers={
                        "Authorization": f"Bearer {access_token}",
                        "Content-Type": "application/json",
                    },
                    json=update_body,
                )
                if resp.status_code != 200:
                    log.error("[GCAL] Update event failed: %s", resp.text)
                    return False
                log.info("[GCAL] Event updated: %s", event_id)
                return True
        except Exception as exc:
            log.error("[GCAL] Update event error: %s", exc)
            return False

    async def cancel_event(self, calendar_id: str, event_id: str) -> bool:
        """Cancel (delete) a calendar event."""
        access_token = await self._get_access_token()
        if not access_token:
            return False

        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.delete(
                    f"{BASE_URL}/calendars/{calendar_id}/events/{event_id}",
                    headers={"Authorization": f"Bearer {access_token}"},
                )
                if resp.status_code not in (200, 204):
                    log.error("[GCAL] Cancel event failed: %s", resp.text)
                    return False
                log.info("[GCAL] Event cancelled: %s", event_id)
                return True
        except Exception as exc:
            log.error("[GCAL] Cancel event error: %s", exc)
            return False

    async def get_upcoming_events(
        self,
        calendar_id: str,
        hours_ahead: int = 24,
    ) -> list[dict]:
        """Get events in the next N hours (for reminders)."""
        access_token = await self._get_access_token()
        if not access_token:
            return []

        now = datetime.utcnow()
        time_max = now + timedelta(hours=hours_ahead)

        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    f"{BASE_URL}/calendars/{calendar_id}/events",
                    headers={"Authorization": f"Bearer {access_token}"},
                    params={
                        "timeMin": now.isoformat() + "Z",
                        "timeMax": time_max.isoformat() + "Z",
                        "singleEvents": "true",
                        "orderBy": "startTime",
                    },
                )
                if resp.status_code != 200:
                    return []

                events = []
                for item in resp.json().get("items", []):
                    start_dt = item.get("start", {}).get("dateTime")
                    end_dt = item.get("end", {}).get("dateTime")
                    if start_dt and end_dt:
                        events.append({
                            "event_id": item["id"],
                            "summary": item.get("summary", ""),
                            "start": start_dt,
                            "end": end_dt,
                            "description": item.get("description", ""),
                        })
                return events
        except Exception as exc:
            log.error("[GCAL] Get upcoming events error: %s", exc)
            return []
