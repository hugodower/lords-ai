from __future__ import annotations

from app.integrations import supabase_client as sb
from app.knowledge.rag import search_knowledge
from app.utils.logger import get_logger

log = get_logger("skill:faq")


async def find_quick_response(org_id: str, message: str) -> str | None:
    """Check if the message matches any quick response trigger."""
    responses = await sb.get_quick_responses(org_id)
    message_lower = message.lower()

    for r in responses:
        keyword = r["trigger_keyword"].lower()
        if keyword in message_lower:
            log.info("FAQ match: '%s'", r["trigger_keyword"])
            return r["response_text"]

    return None


async def search_faq(org_id: str, query: str, limit: int = 3) -> list[str]:
    """Search knowledge base for FAQ-style answers."""
    results = await search_knowledge(org_id, query, limit=limit)
    return [r["text"] for r in results if r.get("score", 0) > 0.5]
