#!/usr/bin/env python3
"""Backfill contacts.channel from Chatwoot conversation inbox data.

Finds all contacts with channel IS NULL, queries Chatwoot for their
conversation history, and updates the channel field based on inbox type.

Usage:
    python scripts/backfill_contact_channels.py          # dry-run (default)
    python scripts/backfill_contact_channels.py --apply   # actually write to DB
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
import time

# Fix Windows console encoding for Portuguese characters
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import httpx
from dotenv import load_dotenv
from supabase import create_client

# ── Load env ────────────────────────────────────────────────────────────
load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_SERVICE_KEY"]
CHATWOOT_URL = os.environ["CHATWOOT_URL"].rstrip("/")
CHATWOOT_TOKEN = os.environ["CHATWOOT_API_TOKEN"]
CHATWOOT_ACCOUNT = os.environ.get("CHATWOOT_ACCOUNT_ID", "1")

# ── Channel mapping (same as supabase_client._CHANNEL_LOWERCASE) ───────
CHANNEL_MAP = {
    "Channel::Api": "whatsapp",
    "Channel::Whatsapp": "whatsapp",
    "Channel::WebWidget": "web",
    "Channel::FacebookPage": "messenger",
    "Channel::Instagram": "instagram",
    "Channel::Email": "email",
    "Channel::Telegram": "telegram",
    "Channel::Sms": "sms",
    "Channel::Line": "line",
}

# Also map from last_channel (capitalized) as fallback
LAST_CHANNEL_MAP = {
    "WhatsApp": "whatsapp",
    "Instagram": "instagram",
    "Messenger": "messenger",
    "Site": "web",
    "Email": "email",
    "Telegram": "telegram",
    "SMS": "sms",
}

RATE_LIMIT_SECONDS = 0.5


async def search_chatwoot_contact(
    client: httpx.AsyncClient, phone: str
) -> str | None:
    """Search Chatwoot for a contact by phone and return the channel type."""
    if not phone:
        return None

    headers = {"api_access_token": CHATWOOT_TOKEN}
    url = f"{CHATWOOT_URL}/api/v1/accounts/{CHATWOOT_ACCOUNT}/search"

    try:
        resp = await client.get(
            url, params={"q": phone, "include_messages": "false"}, headers=headers
        )
        resp.raise_for_status()
        data = resp.json()

        # Search returns {contacts: [...], conversations: [...]}
        conversations = data.get("payload", {}).get("conversations", [])
        if not conversations:
            # Try contacts endpoint for conversations
            contacts = data.get("payload", {}).get("contacts", [])
            if not contacts:
                return None
            # Get first contact's conversations
            cw_contact_id = contacts[0].get("id")
            if cw_contact_id:
                conv_resp = await client.get(
                    f"{CHATWOOT_URL}/api/v1/accounts/{CHATWOOT_ACCOUNT}/contacts/{cw_contact_id}/conversations",
                    headers=headers,
                )
                conv_resp.raise_for_status()
                conv_data = conv_resp.json()
                conversations = conv_data.get("payload", [])

        if not conversations:
            return None

        # Get inbox channel_type from first conversation
        first_conv = conversations[0]
        inbox = first_conv.get("inbox", {}) or {}
        channel_type = inbox.get("channel_type", "")

        if channel_type and channel_type in CHANNEL_MAP:
            return CHANNEL_MAP[channel_type]

        # Fallback: check additional_attributes
        additional = first_conv.get("additional_attributes", {}) or {}
        conv_type = additional.get("type", "")
        if conv_type == "instagram_direct_message":
            return "instagram"
        elif conv_type == "facebook":
            return "messenger"

        return None

    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            return None
        print(f"    HTTP {e.response.status_code} for phone {phone}")
        return None
    except Exception as e:
        print(f"    Error searching {phone}: {e}")
        return None


async def main(apply: bool = False) -> None:
    sb = create_client(SUPABASE_URL, SUPABASE_KEY)

    mode = "APPLY" if apply else "DRY-RUN"
    print(f"\n{'='*60}")
    print(f"  Backfill contact channels [{mode}]")
    print(f"{'='*60}\n")

    # 1) Fetch contacts with channel IS NULL
    print("[1/3] Fetching contacts with channel IS NULL...")
    resp = sb.table("contacts").select(
        "id, name, phone, last_channel, chatwoot_contact_id"
    ).is_("channel", "null").order("created_at").execute()

    contacts = resp.data or []
    print(f"       Found {len(contacts)} contacts without channel\n")

    if not contacts:
        print("Nothing to do!")
        return

    # 2) Try to resolve from last_channel first (no API call needed)
    resolved_from_db = 0
    needs_api = []

    for c in contacts:
        lc = c.get("last_channel")
        if lc and lc in LAST_CHANNEL_MAP:
            channel = LAST_CHANNEL_MAP[lc]
            if apply:
                sb.table("contacts").update({"channel": channel}).eq("id", c["id"]).execute()
            resolved_from_db += 1
            print(f"  DB  {c['name'][:30]:<30} last_channel={lc:<12} -> {channel}")
        else:
            needs_api.append(c)

    print(f"\n[2/3] Resolved {resolved_from_db} from last_channel column")
    print(f"       {len(needs_api)} need Chatwoot API lookup\n")

    # 3) Query Chatwoot API for remaining
    resolved_from_api = 0
    no_channel = 0

    if needs_api:
        print("[3/3] Querying Chatwoot API...")
        async with httpx.AsyncClient(timeout=15) as client:
            for i, c in enumerate(needs_api, 1):
                phone = c.get("phone", "")
                cw_id = c.get("chatwoot_contact_id", "")

                channel = await search_chatwoot_contact(client, phone or cw_id)

                if channel:
                    resolved_from_api += 1
                    if apply:
                        sb.table("contacts").update({"channel": channel}).eq("id", c["id"]).execute()
                    print(f"  API [{i}/{len(needs_api)}] {c['name'][:30]:<30} phone={phone or '—':<15} -> {channel}")
                else:
                    no_channel += 1
                    print(f"  --- [{i}/{len(needs_api)}] {c['name'][:30]:<30} phone={phone or '—':<15} -> NOT FOUND")

                # Rate limiting
                if i < len(needs_api):
                    time.sleep(RATE_LIMIT_SECONDS)
    else:
        print("[3/3] No API lookups needed")

    # Summary
    total = len(contacts)
    updated = resolved_from_db + resolved_from_api
    print(f"\n{'='*60}")
    print(f"  SUMMARY {'(DRY-RUN — nada foi gravado)' if not apply else ''}")
    print(f"{'='*60}")
    print(f"  Total:        {total}")
    print(f"  From DB:      {resolved_from_db} (via last_channel)")
    print(f"  From API:     {resolved_from_api} (via Chatwoot)")
    print(f"  Atualizados:  {updated}")
    print(f"  Sem canal:    {no_channel}")
    print()

    if not apply and updated > 0:
        print("  Para aplicar de verdade, rode com --apply")
        print()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Backfill contacts.channel")
    parser.add_argument("--apply", action="store_true", help="Actually write to DB (default is dry-run)")
    args = parser.parse_args()
    asyncio.run(main(apply=args.apply))
