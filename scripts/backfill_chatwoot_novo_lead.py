#!/usr/bin/env python3
"""Backfill: add 'novo_lead' label to all open Chatwoot conversations.

Fetches all open conversations from Chatwoot, checks if each already has
the 'novo_lead' label, and adds it if missing.

Usage:
    python scripts/backfill_chatwoot_novo_lead.py          # dry-run (default)
    python scripts/backfill_chatwoot_novo_lead.py --apply   # actually add labels
"""
from __future__ import annotations

import argparse
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
ORG_ID = os.environ.get("ORG_ID", "cc000000-0000-0000-0000-000000000001")

LABEL = "novo_lead"
RATE_LIMIT = 0.3  # seconds between requests


def get_chatwoot_creds() -> tuple[str, str, str]:
    """Get Chatwoot credentials from chatwoot_connections table or env."""
    sb = create_client(SUPABASE_URL, SUPABASE_KEY)
    row = (
        sb.table("chatwoot_connections")
        .select("chatwoot_base_url, chatwoot_account_id, chatwoot_api_token")
        .eq("organization_id", ORG_ID)
        .limit(1)
        .execute()
    )
    if row.data:
        conn = row.data[0]
        base = conn["chatwoot_base_url"].rstrip("/")
        acct = str(conn["chatwoot_account_id"])
        token = conn["chatwoot_api_token"]
        print(f"[db] Chatwoot credentials loaded from chatwoot_connections")
        return base, acct, token

    # Fallback to env
    base = os.environ["CHATWOOT_URL"].rstrip("/")
    acct = os.environ.get("CHATWOOT_ACCOUNT_ID", "1")
    token = os.environ["CHATWOOT_API_TOKEN"]
    print(f"[env] Chatwoot credentials loaded from .env")
    return base, acct, token


def fetch_all_open_conversations(
    client: httpx.Client, base: str, acct: str, token: str
) -> list[dict]:
    """Paginate through all open conversations."""
    conversations = []
    page = 1
    while True:
        url = f"{base}/api/v1/accounts/{acct}/conversations"
        resp = client.get(
            url,
            params={"status": "open", "page": page},
            headers={"api_access_token": token},
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()

        payload = data.get("data", {})
        meta = payload.get("meta", data.get("meta", {}))
        items = payload.get("payload", data.get("payload", []))

        if not items:
            break

        conversations.extend(items)
        all_count = meta.get("all_count", 0)
        print(f"  page {page}: {len(items)} conversations (total known: {all_count})")

        if len(conversations) >= all_count or len(items) == 0:
            break

        page += 1
        time.sleep(RATE_LIMIT)

    return conversations


def add_label(
    client: httpx.Client,
    base: str,
    acct: str,
    token: str,
    conv_id: int,
    existing_labels: list[str],
) -> bool:
    """Add 'novo_lead' to conversation labels."""
    new_labels = list(set(existing_labels + [LABEL]))
    url = f"{base}/api/v1/accounts/{acct}/conversations/{conv_id}/labels"
    resp = client.post(
        url,
        json={"labels": new_labels},
        headers={
            "api_access_token": token,
            "Content-Type": "application/json",
        },
        timeout=15,
    )
    return resp.status_code in (200, 201, 204)


def main():
    parser = argparse.ArgumentParser(description="Backfill novo_lead label on open Chatwoot conversations")
    parser.add_argument("--apply", action="store_true", help="Actually add labels (default: dry-run)")
    args = parser.parse_args()

    mode = "APPLY" if args.apply else "DRY-RUN"
    print(f"\n{'='*60}")
    print(f"  Backfill novo_lead — {mode}")
    print(f"  Org: {ORG_ID}")
    print(f"{'='*60}\n")

    base, acct, token = get_chatwoot_creds()
    print(f"  Chatwoot: {base} (account {acct})\n")

    with httpx.Client() as client:
        # 1. Fetch all open conversations
        print("[1/2] Fetching open conversations...")
        conversations = fetch_all_open_conversations(client, base, acct, token)
        total = len(conversations)
        print(f"  Found {total} open conversations\n")

        if total == 0:
            print("Nothing to do.")
            return

        # 2. Check and add labels
        print(f"[2/2] Checking labels ({mode})...\n")
        already = 0
        added = 0
        errors = 0

        for i, conv in enumerate(conversations, 1):
            conv_id = conv.get("id")
            labels = conv.get("labels", [])
            contact = conv.get("meta", {}).get("sender", {})
            name = contact.get("name", "?")

            if LABEL in labels:
                already += 1
                print(f"  [{i}/{total}] Conv #{conv_id} ({name}) — already has novo_lead")
                continue

            if args.apply:
                time.sleep(RATE_LIMIT)
                ok = add_label(client, base, acct, token, conv_id, labels)
                if ok:
                    added += 1
                    print(f"  [{i}/{total}] Conv #{conv_id} ({name}) — ADDED novo_lead")
                else:
                    errors += 1
                    print(f"  [{i}/{total}] Conv #{conv_id} ({name}) — ERROR adding label")
            else:
                added += 1
                print(f"  [{i}/{total}] Conv #{conv_id} ({name}) — WOULD ADD novo_lead")

    # Summary
    print(f"\n{'='*60}")
    print(f"  RESUMO ({mode})")
    print(f"{'='*60}")
    print(f"  Total conversas:      {total}")
    print(f"  Já com novo_lead:     {already}")
    print(f"  {'Adicionado' if args.apply else 'A adicionar'}:          {added}")
    print(f"  Erros:                {errors}")
    print(f"{'='*60}\n")

    if not args.apply and added > 0:
        print("  Para aplicar: python scripts/backfill_chatwoot_novo_lead.py --apply\n")


if __name__ == "__main__":
    main()
