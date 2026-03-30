#!/usr/bin/env python3
"""Fix: remove 'novo_lead' from conversations that have a more advanced stage label.

Fetches all open conversations from Chatwoot, checks if each has BOTH
'novo_lead' AND another stage label, and removes 'novo_lead' if so.

Usage:
    python scripts/fix_chatwoot_novo_lead.py          # dry-run (default)
    python scripts/fix_chatwoot_novo_lead.py --apply   # actually remove labels
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

# Stage labels that indicate the conversation has progressed beyond "novo_lead"
STAGE_LABELS = {
    # Common across templates
    "qualificado",
    "reuniao_agendada",
    "enviar_proposta",
    "em_negociacao",
    "fechou",
    "perdeu",
    # Consultoria
    "diagnostico_ok",
    "apresentacao_feita",
    "contrato_assinado",
    "desistiu",
    # SaaS
    "trial_ativo",
    "demo_agendada",
    "demo_realizada",
    "converteu",
    "churn",
    # B2B
    "primeiro_contato",
    # B2C
    "interessado",
    "atendido",
    "orcamento_enviado",
    "pagou",
    "cancelou",
    # Pós-venda
    "onboarding",
    "acompanhamento",
    "expansao",
    "renovacao",
}


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


def remove_label(
    client: httpx.Client,
    base: str,
    acct: str,
    token: str,
    conv_id: int,
    existing_labels: list[str],
) -> bool:
    """Remove 'novo_lead' from conversation labels by posting all other labels."""
    new_labels = [l for l in existing_labels if l != LABEL]
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
        description="Remove novo_lead from conversations that have advanced stage labels"
    )
    parser.add_argument(
        "--apply", action="store_true", help="Actually remove labels (default: dry-run)"
    )
    args = parser.parse_args()

    mode = "APPLY" if args.apply else "DRY-RUN"
    print(f"\n{'='*60}")
    print(f"  Fix novo_lead — {mode}")
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

        # 2. Check and remove labels
        print(f"[2/2] Checking labels ({mode})...\n")
        no_novo = 0
        only_novo = 0
        removed = 0
        errors = 0

        for i, conv in enumerate(conversations, 1):
            conv_id = conv.get("id")
            labels = conv.get("labels", [])
            contact = conv.get("meta", {}).get("sender", {})
            name = contact.get("name", "?")

            has_novo = LABEL in labels
            advanced = [l for l in labels if l in STAGE_LABELS]

            if not has_novo:
                no_novo += 1
                print(f"  [{i}/{total}] Conv #{conv_id} ({name}) — no novo_lead, skip")
                continue

            if not advanced:
                only_novo += 1
                print(
                    f"  [{i}/{total}] Conv #{conv_id} ({name}) — only novo_lead, keep"
                )
                continue

            # Has novo_lead AND advanced label(s) → remove novo_lead
            adv_str = ", ".join(advanced)
            if args.apply:
                time.sleep(RATE_LIMIT)
                ok = remove_label(client, base, acct, token, conv_id, labels)
                if ok:
                    removed += 1
                    print(
                        f"  [{i}/{total}] Conv #{conv_id} ({name}) — REMOVED novo_lead (has: {adv_str})"
                    )
                else:
                    errors += 1
                    print(
                        f"  [{i}/{total}] Conv #{conv_id} ({name}) — ERROR removing (has: {adv_str})"
                    )
            else:
                removed += 1
                print(
                    f"  [{i}/{total}] Conv #{conv_id} ({name}) — WOULD REMOVE novo_lead (has: {adv_str})"
                )

    # Summary
    print(f"\n{'='*60}")
    print(f"  RESUMO ({mode})")
    print(f"{'='*60}")
    print(f"  Total conversas:      {total}")
    print(f"  Sem novo_lead:        {no_novo}")
    print(f"  Só novo_lead (keep):  {only_novo}")
    print(f"  {'Removido' if args.apply else 'A remover'}:            {removed}")
    print(f"  Erros:                {errors}")
    print(f"{'='*60}\n")

    if not args.apply and removed > 0:
        print(
            "  Para aplicar: python scripts/fix_chatwoot_novo_lead.py --apply\n"
        )


if __name__ == "__main__":
    main()
