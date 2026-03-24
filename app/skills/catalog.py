from __future__ import annotations

from app.integrations import supabase_client as sb
from app.utils.logger import get_logger

log = get_logger("skill:catalog")


async def get_catalog_text(org_id: str) -> str:
    """Get formatted product catalog for the org."""
    products = await sb.get_products(org_id)
    if not products:
        return "Nenhum produto/serviço cadastrado no momento."

    lines = []
    for p in products:
        price = p.get("unit_price")
        price_str = f"R$ {price:.2f}" if price else "sob consulta"
        desc = p.get("description", "")
        lines.append(f"• {p['name']} — {price_str}")
        if desc:
            lines.append(f"  {desc}")

    return "\n".join(lines)


async def find_product_by_name(org_id: str, query: str) -> list[dict]:
    """Search products matching a query (simple substring match)."""
    products = await sb.get_products(org_id)
    query_lower = query.lower()
    return [
        p for p in products
        if query_lower in p.get("name", "").lower()
        or query_lower in p.get("description", "").lower()
    ]
