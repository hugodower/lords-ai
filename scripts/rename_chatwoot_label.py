#!/usr/bin/env python3
"""Rename a Chatwoot label on all open conversations.

Fetches all open conversations, finds those with the OLD label,
and replaces it with the NEW label.

Usage:
    python scripts/rename_chatwoot_label.py                        # dry-run (default)
    python scripts/rename_chatwoot_label.py --apply                # actually rename
    python scripts/rename_chatwoot_label.py --old X --new Y        # custom labels
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


def set_labels(
    client: httpx.Client,
    base: str,
    acct: str,
    token: str,
    conv_id: int,
    new_labels: list[str],
) -> bool:
    """Set the full label list on a conversation."""
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
    parser = argparse.ArgumentParser(
        description="Rename a Chatwoot label on all open conversations"
    )
    parser.add_argument(
        "--apply", action="store_true", help="Actually rename (default: dry-run)"
    )
    parser.add_argument(
        "--old", default="proposta_enviada", help="Old label name (default: proposta_enviada)"
    )
    parser.add_argument(
        "--new", default="enviar_proposta", help="New label name (default: enviar_proposta)"
    )
    args = parser.parse_args()

    old_label = args.old
    new_label = args.new
    mode = "APPLY" if args.apply else "DRY-RUN"

    print(f"\n{'='*60}")
    print(f"  Rename Chatwoot Label — {mode}")
    print(f"  {old_label} → {new_label}")
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

        # 2. Rename labels
        print(f"[2/2] Renaming labels ({mode})...\n")
        no_old = 0
        renamed = 0
        errors = 0

        for i, conv in enumerate(conversations, 1):
            conv_id = conv.get("id")
            labels = conv.get("labels", [])
            contact = conv.get("meta", {}).get("sender", {})
            name = contact.get("name", "?")

            if old_label not in labels:
                no_old += 1
                continue

            # Build new label list: replace old with new
            new_labels = [new_label if l == old_label else l for l in labels]

            if args.apply:
                time.sleep(RATE_LIMIT)
                ok = set_labels(client, base, acct, token, conv_id, new_labels)
                if ok:
                    renamed += 1
                    print(
                        f"  [{i}/{total}] Conv #{conv_id} ({name}) — RENAMED {old_label} → {new_label}"
                    )
                else:
                    errors += 1
                    print(
                        f"  [{i}/{total}] Conv #{conv_id} ({name}) — ERROR renaming"
                    )
            else:
                renamed += 1
                print(
                    f"  [{i}/{total}] Conv #{conv_id} ({name}) — WOULD RENAME {old_label} → {new_label}"
                )

    # Summary
    print(f"\n{'='*60}")
    print(f"  RESUMO ({mode})")
    print(f"{'='*60}")
    print(f"  Total conversas:      {total}")
    print(f"  Sem {old_label}:  {no_old}")
    print(f"  {'Renomeado' if args.apply else 'A renomear'}:           {renamed}")
    print(f"  Erros:                {errors}")
    print(f"{'='*60}\n")

    if not args.apply and renamed > 0:
        print(
            f"  Para aplicar: python scripts/rename_chatwoot_label.py --apply\n"
        )


if __name__ == "__main__":
    main()
