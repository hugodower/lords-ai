#!/usr/bin/env python3
"""Backfill contacts.city/state/country from Brazilian phone DDD.

Extracts the 2-digit area code (DDD) from the contact's phone number
and maps it to the main city, state, and country.

Usage:
    python scripts/backfill_contact_location.py          # dry-run (default)
    python scripts/backfill_contact_location.py --apply   # actually write to DB
"""
from __future__ import annotations

import argparse
import asyncio
import os
import re
import sys

# Fix Windows console encoding for Portuguese characters
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from dotenv import load_dotenv
from supabase import create_client

# ── Load env ────────────────────────────────────────────────────────────
load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_SERVICE_KEY"]

# ── Complete Brazilian DDD → city/state/country mapping (67 DDDs) ────
# Source: ANATEL area code assignments — main city per DDD
DDD_MAP: dict[str, dict[str, str]] = {
    # São Paulo (state)
    "11": {"city": "São Paulo", "state": "SP", "country": "Brasil"},
    "12": {"city": "São José dos Campos", "state": "SP", "country": "Brasil"},
    "13": {"city": "Santos", "state": "SP", "country": "Brasil"},
    "14": {"city": "Bauru", "state": "SP", "country": "Brasil"},
    "15": {"city": "Sorocaba", "state": "SP", "country": "Brasil"},
    "16": {"city": "Ribeirão Preto", "state": "SP", "country": "Brasil"},
    "17": {"city": "São José do Rio Preto", "state": "SP", "country": "Brasil"},
    "18": {"city": "Presidente Prudente", "state": "SP", "country": "Brasil"},
    "19": {"city": "Campinas", "state": "SP", "country": "Brasil"},
    # Rio de Janeiro (state)
    "21": {"city": "Rio de Janeiro", "state": "RJ", "country": "Brasil"},
    "22": {"city": "Campos dos Goytacazes", "state": "RJ", "country": "Brasil"},
    "24": {"city": "Volta Redonda", "state": "RJ", "country": "Brasil"},
    # Espírito Santo
    "27": {"city": "Vitória", "state": "ES", "country": "Brasil"},
    "28": {"city": "Cachoeiro de Itapemirim", "state": "ES", "country": "Brasil"},
    # Minas Gerais
    "31": {"city": "Belo Horizonte", "state": "MG", "country": "Brasil"},
    "32": {"city": "Juiz de Fora", "state": "MG", "country": "Brasil"},
    "33": {"city": "Governador Valadares", "state": "MG", "country": "Brasil"},
    "34": {"city": "Uberlândia", "state": "MG", "country": "Brasil"},
    "35": {"city": "Poços de Caldas", "state": "MG", "country": "Brasil"},
    "37": {"city": "Divinópolis", "state": "MG", "country": "Brasil"},
    "38": {"city": "Montes Claros", "state": "MG", "country": "Brasil"},
    # Paraná
    "41": {"city": "Curitiba", "state": "PR", "country": "Brasil"},
    "42": {"city": "Ponta Grossa", "state": "PR", "country": "Brasil"},
    "43": {"city": "Londrina", "state": "PR", "country": "Brasil"},
    "44": {"city": "Maringá", "state": "PR", "country": "Brasil"},
    "45": {"city": "Foz do Iguaçu", "state": "PR", "country": "Brasil"},
    "46": {"city": "Francisco Beltrão", "state": "PR", "country": "Brasil"},
    # Santa Catarina
    "47": {"city": "Joinville", "state": "SC", "country": "Brasil"},
    "48": {"city": "Florianópolis", "state": "SC", "country": "Brasil"},
    "49": {"city": "Chapecó", "state": "SC", "country": "Brasil"},
    # Rio Grande do Sul
    "51": {"city": "Porto Alegre", "state": "RS", "country": "Brasil"},
    "53": {"city": "Pelotas", "state": "RS", "country": "Brasil"},
    "54": {"city": "Caxias do Sul", "state": "RS", "country": "Brasil"},
    "55": {"city": "Santa Maria", "state": "RS", "country": "Brasil"},
    # Distrito Federal / Goiás
    "61": {"city": "Brasília", "state": "DF", "country": "Brasil"},
    "62": {"city": "Goiânia", "state": "GO", "country": "Brasil"},
    "64": {"city": "Rio Verde", "state": "GO", "country": "Brasil"},
    # Tocantins
    "63": {"city": "Palmas", "state": "TO", "country": "Brasil"},
    # Mato Grosso do Sul
    "67": {"city": "Campo Grande", "state": "MS", "country": "Brasil"},
    # Mato Grosso
    "65": {"city": "Cuiabá", "state": "MT", "country": "Brasil"},
    "66": {"city": "Rondonópolis", "state": "MT", "country": "Brasil"},
    # Acre
    "68": {"city": "Rio Branco", "state": "AC", "country": "Brasil"},
    # Rondônia
    "69": {"city": "Porto Velho", "state": "RO", "country": "Brasil"},
    # Amazonas
    "92": {"city": "Manaus", "state": "AM", "country": "Brasil"},
    "97": {"city": "Manaus", "state": "AM", "country": "Brasil"},
    # Roraima
    "95": {"city": "Boa Vista", "state": "RR", "country": "Brasil"},
    # Pará
    "91": {"city": "Belém", "state": "PA", "country": "Brasil"},
    "93": {"city": "Santarém", "state": "PA", "country": "Brasil"},
    "94": {"city": "Marabá", "state": "PA", "country": "Brasil"},
    # Amapá
    "96": {"city": "Macapá", "state": "AP", "country": "Brasil"},
    # Maranhão
    "98": {"city": "São Luís", "state": "MA", "country": "Brasil"},
    "99": {"city": "Imperatriz", "state": "MA", "country": "Brasil"},
    # Piauí
    "86": {"city": "Teresina", "state": "PI", "country": "Brasil"},
    "89": {"city": "Picos", "state": "PI", "country": "Brasil"},
    # Ceará
    "85": {"city": "Fortaleza", "state": "CE", "country": "Brasil"},
    "88": {"city": "Juazeiro do Norte", "state": "CE", "country": "Brasil"},
    # Rio Grande do Norte
    "84": {"city": "Natal", "state": "RN", "country": "Brasil"},
    # Paraíba
    "83": {"city": "João Pessoa", "state": "PB", "country": "Brasil"},
    # Pernambuco
    "81": {"city": "Recife", "state": "PE", "country": "Brasil"},
    "87": {"city": "Petrolina", "state": "PE", "country": "Brasil"},
    # Alagoas
    "82": {"city": "Maceió", "state": "AL", "country": "Brasil"},
    # Sergipe
    "79": {"city": "Aracaju", "state": "SE", "country": "Brasil"},
    # Bahia
    "71": {"city": "Salvador", "state": "BA", "country": "Brasil"},
    "73": {"city": "Ilhéus", "state": "BA", "country": "Brasil"},
    "74": {"city": "Juazeiro", "state": "BA", "country": "Brasil"},
    "75": {"city": "Feira de Santana", "state": "BA", "country": "Brasil"},
    "77": {"city": "Vitória da Conquista", "state": "BA", "country": "Brasil"},
}


def extract_ddd(phone: str) -> str | None:
    """Extract 2-digit DDD from a Brazilian phone number.

    Handles: "5518996597391", "+5518996597391", "18996597391", "996597391"
    """
    digits = re.sub(r"\D", "", phone)
    if not digits:
        return None

    # Remove country code 55
    if digits.startswith("55") and len(digits) >= 12:
        digits = digits[2:]

    # Now we expect DDD (2 digits) + number (8-9 digits) = 10-11 digits
    if len(digits) >= 10:
        ddd = digits[:2]
        if ddd in DDD_MAP:
            return ddd

    return None


async def main(apply: bool = False) -> None:
    sb = create_client(SUPABASE_URL, SUPABASE_KEY)

    mode = "APPLY" if apply else "DRY-RUN"
    print(f"\n{'='*60}")
    print(f"  Backfill contact location from DDD [{mode}]")
    print(f"{'='*60}\n")

    # Check if 'state' column exists
    print("[0/3] Verificando coluna 'state' na tabela contacts...")
    try:
        test = sb.table("contacts").select("state").limit(1).execute()
        print("       Coluna 'state' existe ✓\n")
    except Exception as e:
        err_msg = str(e)
        if "state" in err_msg.lower() or "column" in err_msg.lower() or "400" in err_msg:
            print("       ⚠ Coluna 'state' NÃO existe na tabela contacts!")
            print("       Execute no Supabase SQL Editor:")
            print("       ALTER TABLE public.contacts ADD COLUMN IF NOT EXISTS state VARCHAR(50);")
            print()
            return
        else:
            raise

    # 1) Fetch contacts with city IS NULL and phone not empty
    print("[1/3] Buscando contatos com city IS NULL e phone preenchido...")
    resp = (
        sb.table("contacts")
        .select("id, name, phone, city, state, country")
        .is_("city", "null")
        .neq("phone", "")
        .order("created_at")
        .execute()
    )

    contacts = resp.data or []
    # Filter out contacts with NULL phone (neq doesn't filter NULL)
    contacts = [c for c in contacts if c.get("phone")]
    print(f"       Encontrados {len(contacts)} contatos sem city e com phone\n")

    if not contacts:
        print("Nada a fazer!")
        return

    # 2) Map DDDs and update
    print("[2/3] Mapeando DDDs...")
    updated = 0
    no_ddd = 0
    by_state: dict[str, int] = {}

    for c in contacts:
        phone = c.get("phone", "")
        ddd = extract_ddd(phone)

        if not ddd:
            no_ddd += 1
            print(f"  --- {c['name'][:30]:<30} phone={phone:<15} → DDD não encontrado")
            continue

        location = DDD_MAP[ddd]
        city = location["city"]
        state = location["state"]
        country = location["country"]

        by_state[state] = by_state.get(state, 0) + 1

        if apply:
            sb.table("contacts").update({
                "city": city,
                "state": state,
                "country": country,
            }).eq("id", c["id"]).execute()

        updated += 1
        print(f"  ✓   {c['name'][:30]:<30} phone={phone:<15} → DDD {ddd} → {city}/{state}")

    # 3) Summary
    total = len(contacts)
    print(f"\n{'='*60}")
    print(f"  RESUMO {'(DRY-RUN — nada foi gravado)' if not apply else ''}")
    print(f"{'='*60}")
    print(f"  Total:              {total}")
    print(f"  Atualizados:        {updated}")
    print(f"  Sem DDD mapeado:    {no_ddd}")
    print()

    if by_state:
        print("  Por estado:")
        for st, count in sorted(by_state.items(), key=lambda x: -x[1]):
            print(f"    {st}: {count}")
        print()

    if not apply and updated > 0:
        print("  Para aplicar de verdade, rode com --apply")
        print()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Backfill contacts location from DDD")
    parser.add_argument("--apply", action="store_true", help="Actually write to DB (default is dry-run)")
    args = parser.parse_args()
    asyncio.run(main(apply=args.apply))
