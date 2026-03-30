#!/usr/bin/env python3
"""Cleanup: resolve open Chatwoot conversations that have no agent assigned.

Fetches all open conversations, filters those without an assignee,
and resolves them (toggle_status → resolved).

Usage:
    python scripts/cleanup_chatwoot_conversations.py          # dry-run (default)
    python scripts/cleanup_chatwoot_conversations.py --apply   # actually resolve
"""
from __future__ import annotations

import argparse
import os
import sys
import time

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import httpx
from dotenv import load_dotenv
from supabase import create_client

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_SERVICE_KEY"]
ORG_ID = os.environ.get("ORG_ID", "cc000000-0000-0000-0000-000000000001")

RATE_LIMIT = 0.5


def get_chatwoot_creds() -> tuple[str, str, str]:
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

    base = os.environ["CHATWOOT_URL"].rstrip("/")
    acct = os.environ.get("CHATWOOT_ACCOUNT_ID", "1")
    token = os.environ["CHATWOOT_API_TOKEN"]
    print(f"[env] Chatwoot credentials loaded from .env")
    return base, acct, token


def fetch_all_open_conversations(
    client: httpx.Client, base: str, acct: str, token: str
) -> list[dict]:
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


def resolve_conversation(
    client: httpx.Client, base: str, acct: str, token: str, conv_id: int
) -> bool:
    url = f"{base}/api/v1/accounts/{acct}/conversations/{conv_id}/toggle_status"
    resp = client.post(
        url,
        json={"status": "resolved"},
        headers={
            "api_access_token": token,
            "Content-Type": "application/json",
        },
        timeout=15,
    )
    return resp.status_code in (200, 201, 204)


def main():
    parser = argparse.ArgumentParser(
        description="Resolve open Chatwoot conversations without an assigned agent"
    )
    parser.add_argument(
        "--apply", action="store_true", help="Actually resolve (default: dry-run)"
    )
    args = parser.parse_args()

    mode = "APPLY" if args.apply else "DRY-RUN"
    print(f"\n{'='*60}")
    print(f"  Cleanup Conversations — {mode}")
    print(f"  Org: {ORG_ID}")
    print(f"{'='*60}\n")

    base, acct, token = get_chatwoot_creds()
    print(f"  Chatwoot: {base} (account {acct})\n")

    with httpx.Client() as client:
        print("[1/2] Fetching open conversations...")
        conversations = fetch_all_open_conversations(client, base, acct, token)
        total = len(conversations)
        print(f"  Found {total} open conversations\n")

        if total == 0:
            print("Nothing to do.")
            return

        # Filter: no assignee
        unassigned = []
        assigned = 0
        for conv in conversations:
            assignee = conv.get("meta", {}).get("assignee") or conv.get("assignee")
            if assignee:
                assigned += 1
            else:
                unassigned.append(conv)

        print(f"  With agent: {assigned} (skip)")
        print(f"  Without agent: {len(unassigned)} (to resolve)\n")

        if not unassigned:
            print("All conversations have agents assigned. Nothing to do.")
            return

        print(f"[2/2] Resolving ({mode})...\n")
        resolved = 0
        errors = 0

        for i, conv in enumerate(unassigned, 1):
            conv_id = conv.get("id")
            contact = conv.get("meta", {}).get("sender", {})
            name = contact.get("name", "?")
            labels = conv.get("labels", [])
            label_str = ", ".join(labels[:3]) if labels else "—"

            if args.apply:
                time.sleep(RATE_LIMIT)
                ok = resolve_conversation(client, base, acct, token, conv_id)
                if ok:
                    resolved += 1
                    print(f"  [{i}/{len(unassigned)}] Conv #{conv_id} ({name}) [{label_str}] — RESOLVED")
                else:
                    errors += 1
                    print(f"  [{i}/{len(unassigned)}] Conv #{conv_id} ({name}) [{label_str}] — ERROR")
            else:
                resolved += 1
                print(f"  [{i}/{len(unassigned)}] Conv #{conv_id} ({name}) [{label_str}] — WOULD RESOLVE")

    print(f"\n{'='*60}")
    print(f"  RESUMO ({mode})")
    print(f"{'='*60}")
    print(f"  Total abertas:        {total}")
    print(f"  Com agente (skip):    {assigned}")
    print(f"  Sem agente:           {len(unassigned)}")
    print(f"  {'Resolvidas' if args.apply else 'A resolver'}:          {resolved}")
    print(f"  Erros:                {errors}")
    print(f"{'='*60}\n")

    if not args.apply and resolved > 0:
        print("  Para aplicar: python scripts/cleanup_chatwoot_conversations.py --apply\n")


if __name__ == "__main__":
    main()
