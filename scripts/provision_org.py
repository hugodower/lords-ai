#!/usr/bin/env python3
"""
Provision a new organization in the lords-ai Supabase database.

Creates all required records across ~9 tables so the AI agent
can serve the new org immediately after Chatwoot/WhatsApp setup.

Usage:
  python scripts/provision_org.py \
    --org-id "UUID" \
    --agent-name "Sofia" \
    --company-name "Clínica Odonto Premium"

  python scripts/provision_org.py --dry-run \
    --org-id "UUID" --agent-name "Test" --company-name "Test Inc"
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Env loading (same pattern as app/config.py — reads .env then .env.deploy)
# ---------------------------------------------------------------------------

def _load_env(path: str) -> None:
    p = Path(path)
    if not p.exists():
        return
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())


# Load from project root
_project_root = Path(__file__).parent.parent
_load_env(str(_project_root / ".env"))
_load_env(str(_project_root / ".env.deploy"))
_load_env(str(_project_root / ".env.local"))

SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_KEY", "") or os.environ.get("SUPABASE_KEY", "")

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

DEFAULT_PERSONALITY = (
    "Profissional, simpática e objetiva. Usa linguagem informal mas respeitosa. "
    "Sempre busca entender a necessidade do cliente antes de oferecer soluções. "
    "Usa emojis com moderação (máximo 2 por mensagem). Responde de forma curta "
    "e direta, especialmente no WhatsApp."
)

DEFAULT_BUSINESS_HOURS = [
    {"day_of_week": 0, "is_open": True,  "open_time": "09:00", "close_time": "18:00"},
    {"day_of_week": 1, "is_open": True,  "open_time": "09:00", "close_time": "18:00"},
    {"day_of_week": 2, "is_open": True,  "open_time": "09:00", "close_time": "18:00"},
    {"day_of_week": 3, "is_open": True,  "open_time": "09:00", "close_time": "18:00"},
    {"day_of_week": 4, "is_open": True,  "open_time": "09:00", "close_time": "18:00"},
    {"day_of_week": 5, "is_open": False, "open_time": "09:00", "close_time": "13:00"},
    {"day_of_week": 6, "is_open": False, "open_time": None,    "close_time": None},
]

DEFAULT_QUALIFICATION_STEPS = [
    {"step_order": 1, "question": "Qual o segmento/tipo do seu negócio?",                                    "is_required": True},
    {"step_order": 2, "question": "Quantas pessoas fazem parte da equipe comercial/atendimento?",             "is_required": True},
    {"step_order": 3, "question": "Qual a principal dificuldade que enfrenta hoje no atendimento/vendas?",    "is_required": True},
    {"step_order": 4, "question": "Já utiliza alguma ferramenta de CRM ou atendimento?",                      "is_required": False},
]

DEFAULT_HOT_CRITERIA = (
    "Lead demonstra interesse claro em agendar reunião, solicita preços ou "
    "prazos, ou pede para falar com um consultor."
)


# ---------------------------------------------------------------------------
# Supabase helpers
# ---------------------------------------------------------------------------

def get_client():
    from supabase import create_client
    if not SUPABASE_URL or not SUPABASE_KEY:
        print("[ERROR] SUPABASE_URL and SUPABASE_SERVICE_KEY must be set.")
        print("        Checked: .env, .env.deploy, .env.local, and environment variables.")
        sys.exit(1)
    return create_client(SUPABASE_URL, SUPABASE_KEY)


def upsert_single(sb, table: str, data: dict, conflict_col: str = "organization_id") -> str:
    """Insert or skip if conflict on unique constraint. Returns 'created' or 'exists'."""
    try:
        resp = (
            sb.table(table)
            .select("id")
            .eq(conflict_col, data[conflict_col])
            .limit(1)
            .execute()
        )
        if resp.data:
            return "exists"
    except Exception:
        pass

    try:
        sb.table(table).insert(data).execute()
        return "created"
    except Exception as exc:
        err = str(exc)
        if "duplicate" in err.lower() or "unique" in err.lower() or "23505" in err:
            return "exists"
        raise


def upsert_multi(sb, table: str, rows: list[dict], conflict_cols: list[str]) -> tuple[int, int]:
    """Insert multiple rows, skipping existing. Returns (created, skipped)."""
    created = 0
    skipped = 0
    for row in rows:
        try:
            # Check existence
            query = sb.table(table).select("id")
            for col in conflict_cols:
                query = query.eq(col, row[col])
            existing = query.limit(1).execute()
            if existing.data:
                skipped += 1
                continue
        except Exception:
            pass

        try:
            sb.table(table).insert(row).execute()
            created += 1
        except Exception as exc:
            err = str(exc)
            if "duplicate" in err.lower() or "unique" in err.lower() or "23505" in err:
                skipped += 1
            else:
                raise
    return created, skipped


# ---------------------------------------------------------------------------
# Provisioning steps
# ---------------------------------------------------------------------------

def provision(args) -> dict:
    """Run all provisioning steps. Returns summary dict."""
    sb = get_client()
    org_id = args.org_id
    results = {}
    errors = []

    # ── Validate org exists ──
    try:
        resp = sb.table("organizations").select("id, name").eq("id", org_id).maybe_single().execute()
        if not resp or not resp.data:
            print(f"[ERROR] Organização não encontrada: {org_id}")
            print("        O org_id deve existir na tabela 'organizations' antes de provisionar.")
            sys.exit(1)
        org_name = resp.data.get("name", "?")
        print(f"[OK] Organização encontrada: {org_name} ({org_id})")
    except Exception as exc:
        print(f"[ERROR] Falha ao verificar organização: {exc}")
        sys.exit(1)

    # ── 1. agent_configs ──
    try:
        status = upsert_single(sb, "agent_configs", {
            "organization_id": org_id,
            "agent_type": args.agent_type,
            "agent_name": args.agent_name,
            "personality": args.personality or DEFAULT_PERSONALITY,
            "is_active": True,
            "max_messages": args.max_messages,
            "max_response_time_seconds": 10,
            "handoff_agent_id": None,
            "handoff_agent_name": None,
            "claude_api_key": None,
        })
        results["agent_configs"] = f"1 registro ({status})"
    except Exception as exc:
        results["agent_configs"] = f"ERRO: {exc}"
        errors.append(("agent_configs", exc))

    # ── 2. company_info ──
    try:
        status = upsert_single(sb, "company_info", {
            "organization_id": org_id,
            "company_name": args.company_name,
            "segment": args.segment or "",
            "description": args.description or "",
            "website": args.website or "",
            "address": "",
            "payment_methods": "",
            "differentials": "",
        })
        results["company_info"] = f"1 registro ({status})"
    except Exception as exc:
        results["company_info"] = f"ERRO: {exc}"
        errors.append(("company_info", exc))

    # ── 3. business_hours ──
    try:
        rows = [{"organization_id": org_id, **day} for day in DEFAULT_BUSINESS_HOURS]
        created, skipped = upsert_multi(sb, "business_hours", rows, ["organization_id", "day_of_week"])
        results["business_hours"] = f"{created} criados, {skipped} existentes (total 7)"
    except Exception as exc:
        results["business_hours"] = f"ERRO: {exc}"
        errors.append(("business_hours", exc))

    # ── 4. business_hours_config ──
    try:
        status = upsert_single(sb, "business_hours_config", {
            "organization_id": org_id,
            "after_hours_message": (
                "Olá! No momento estamos fora do horário de atendimento. "
                "Nosso time funciona de segunda a sexta, das 9h às 18h. "
                "Mas pode deixar sua mensagem que retornamos assim que possível! 😊"
            ),
            "after_hours_behavior": "reply_and_qualify",
        })
        results["business_hours_config"] = f"1 registro ({status})"
    except Exception as exc:
        results["business_hours_config"] = f"ERRO: {exc}"
        errors.append(("business_hours_config", exc))

    # ── 5. qualification_steps ──
    try:
        rows = [
            {"organization_id": org_id, "agent_type": args.agent_type, **step}
            for step in DEFAULT_QUALIFICATION_STEPS
        ]
        created, skipped = upsert_multi(
            sb, "qualification_steps", rows,
            ["organization_id", "agent_type", "step_order"],
        )
        results["qualification_steps"] = f"{created} criadas, {skipped} existentes (total 4)"
    except Exception as exc:
        results["qualification_steps"] = f"ERRO: {exc}"
        errors.append(("qualification_steps", exc))

    # ── 6. lead_hot_criteria ──
    try:
        status = upsert_single(sb, "lead_hot_criteria", {
            "organization_id": org_id,
            "criteria_description": DEFAULT_HOT_CRITERIA,
        })
        results["lead_hot_criteria"] = f"1 registro ({status})"
    except Exception as exc:
        results["lead_hot_criteria"] = f"ERRO: {exc}"
        errors.append(("lead_hot_criteria", exc))

    # ── 7. followup_config ──
    try:
        status = upsert_single(sb, "followup_config", {
            "organization_id": org_id,
            "followup_enabled": True,
            "followup_24h_enabled": True,
            "followup_48h_enabled": True,
            "reativacao_7d_enabled": True,
            "confirmacao_enabled": True,
            "lembrete_enabled": True,
        })
        results["followup_config"] = f"1 registro ({status})"
    except Exception as exc:
        results["followup_config"] = f"ERRO: {exc}"
        errors.append(("followup_config", exc))

    # ── 8. chatwoot_connections (empty shell) ──
    try:
        status = upsert_single(sb, "chatwoot_connections", {
            "organization_id": org_id,
            "chatwoot_base_url": "",
            "chatwoot_account_id": None,
            "chatwoot_api_token": "",
            "phone_number_id": "",
            "connection_status": "not_configured",
            "chatwoot_status": "not_configured",
            "n8n_status": "not_configured",
        })
        results["chatwoot_connections"] = f"1 registro ({status})"
    except Exception as exc:
        results["chatwoot_connections"] = f"ERRO: {exc}"
        errors.append(("chatwoot_connections", exc))

    # ── 9. scheduling_config ──
    try:
        status = upsert_single(sb, "scheduling_config", {
            "organization_id": org_id,
            "scheduling_type": "collect_preference",
            "slot_duration_minutes": 30,
            "buffer_minutes": 15,
            "google_calendar_id": None,
            "google_oauth_token": None,
        })
        results["scheduling_config"] = f"1 registro ({status})"
    except Exception as exc:
        results["scheduling_config"] = f"ERRO: {exc}"
        errors.append(("scheduling_config", exc))

    return {
        "org_id": org_id,
        "org_name": org_name,
        "agent_name": args.agent_name,
        "agent_type": args.agent_type,
        "company_name": args.company_name,
        "segment": args.segment or "não informado",
        "results": results,
        "errors": errors,
    }


def print_summary(summary: dict) -> None:
    """Print the final provisioning report."""
    results = summary["results"]
    errors = summary["errors"]

    print()
    print("=" * 55)
    print("  PROVISIONING COMPLETO — Nova Organização")
    print("=" * 55)
    print()
    print(f"  Org ID:       {summary['org_id']}")
    print(f"  Org Name:     {summary['org_name']}")
    print(f"  Agente:       {summary['agent_name']} (tipo: {summary['agent_type']})")
    print(f"  Empresa:      {summary['company_name']}")
    print(f"  Segmento:     {summary['segment']}")
    print()
    print("  Registros:")

    for table, status in results.items():
        icon = "x" if "ERRO" in status else "v"
        print(f"  [{icon}] {table:25s} — {status}")

    if errors:
        print()
        print(f"  ERROS ({len(errors)}):")
        for table, exc in errors:
            print(f"    - {table}: {exc}")

    print()
    print("  PRÓXIMOS PASSOS:")
    print("  1. Configurar Chatwoot e inserir credenciais em chatwoot_connections")
    print("  2. Configurar WhatsApp Cloud API (phone_number_id + access_token)")
    print("  3. Adicionar produtos/serviços no catálogo via painel CRM")
    print("  4. Personalizar perguntas de qualificação via painel CRM")
    print("  5. (Opcional) Configurar Google Calendar para agendamento automático")
    print("  6. Criar usuário virtual do agente IA no Chatwoot da org")
    print()
    print("=" * 55)


def print_dry_run(args) -> None:
    """Show what would be created without executing."""
    print()
    print("=" * 55)
    print("  DRY RUN — Nenhum dado será criado")
    print("=" * 55)
    print()
    print(f"  Org ID:       {args.org_id}")
    print(f"  Agente:       {args.agent_name} (tipo: {args.agent_type})")
    print(f"  Empresa:      {args.company_name}")
    print(f"  Segmento:     {args.segment or 'não informado'}")
    print()
    print("  Tabelas que seriam provisionadas:")
    print(f"  - agent_configs         — 1 registro ({args.agent_type}, ativo)")
    print(f"  - company_info          — 1 registro ({args.company_name})")
    print(f"  - business_hours        — 7 registros (seg-sex 9h-18h)")
    print(f"  - business_hours_config — 1 registro (reply_and_qualify)")
    print(f"  - qualification_steps   — 4 perguntas padrão SDR")
    print(f"  - lead_hot_criteria     — 1 critério padrão")
    print(f"  - followup_config       — 1 registro (todos habilitados)")
    print(f"  - chatwoot_connections  — 1 registro (vazio, preencher depois)")
    print(f"  - scheduling_config     — 1 registro (collect_preference)")
    print()
    print("  Tabelas vazias (sob demanda):")
    print(f"  - quick_responses       — org admin adiciona pelo painel")
    print(f"  - forbidden_topics      — org admin adiciona pelo painel")
    print(f"  - products              — org admin adiciona pelo painel")
    print()
    print(f"  Personalidade: {(args.personality or DEFAULT_PERSONALITY)[:80]}...")
    print()
    print("=" * 55)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Provisiona uma nova organização no Supabase para o lords-ai.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Exemplos:\n"
            "  python scripts/provision_org.py \\\n"
            '    --org-id "abc123..." --agent-name "Sofia" --company-name "Clínica Premium"\n'
            "\n"
            "  python scripts/provision_org.py --dry-run \\\n"
            '    --org-id "abc123..." --agent-name "Test" --company-name "Test"\n'
        ),
    )

    parser.add_argument("--org-id", required=True, help="UUID da organização (deve existir em organizations)")
    parser.add_argument("--agent-name", required=True, help="Nome do agente IA (ex: Sofia, Luna, Ana)")
    parser.add_argument("--company-name", required=True, help="Nome da empresa (ex: Clínica Odonto Premium)")

    parser.add_argument("--segment", default="", help="Segmento da empresa (default: vazio)")
    parser.add_argument("--description", default="", help="Descrição da empresa (default: vazio)")
    parser.add_argument("--website", default="", help="Website da empresa (default: vazio)")
    parser.add_argument("--agent-type", default="sdr", choices=["sdr", "support", "closer", "retention"],
                        help="Tipo do agente (default: sdr)")
    parser.add_argument("--personality", default="", help="Personalidade do agente (default: texto padrão)")
    parser.add_argument("--max-messages", type=int, default=30, help="Limite de msgs por conversa (default: 30)")
    parser.add_argument("--dry-run", action="store_true", help="Mostra o que seria criado sem executar")

    args = parser.parse_args()

    if args.dry_run:
        print_dry_run(args)
        return

    print(f"[PROVISION] Iniciando provisionamento para org {args.org_id}...")
    print(f"[PROVISION] Supabase: {SUPABASE_URL}")
    print()

    summary = provision(args)
    print_summary(summary)

    if summary["errors"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
