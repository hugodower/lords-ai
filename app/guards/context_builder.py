from __future__ import annotations

from pathlib import Path
from typing import Optional

from app.integrations import supabase_client as sb
from app.memory.redis_store import get_conversation_history
from app.knowledge.rag import search_knowledge
from app.utils.logger import get_logger

log = get_logger("context_builder")

TEMPLATES_DIR = Path(__file__).parent.parent.parent / "templates"


def _load_template(agent_type: str) -> str:
    template_path = TEMPLATES_DIR / f"{agent_type}_system_prompt.md"
    if template_path.exists():
        return template_path.read_text(encoding="utf-8")
    log.warning("Template not found: %s", template_path)
    return ""


async def build_context(
    org_id: str,
    agent_type: str,
    agent_config: dict,
    conversation_id: str,
    contact_name: str,
    contact_phone: str,
    user_message: str,
) -> str:
    """Build the full system prompt with verified data from Supabase."""

    template = _load_template(agent_type)
    if not template:
        return ""

    # Fetch all data in parallel-ish (sync Supabase calls)
    company = await sb.get_company_info(org_id)
    products = await sb.get_products(org_id)
    steps = await sb.get_qualification_steps(org_id, agent_type)
    faq = await sb.get_quick_responses(org_id)
    forbidden = await sb.get_forbidden_topics(org_id)
    hot_criteria = await sb.get_hot_criteria(org_id)
    # Conversation history from Redis
    history = await get_conversation_history(conversation_id)

    # RAG search for relevant knowledge
    rag_results = await search_knowledge(org_id, user_message, limit=3)

    # Format products list
    products_text = "\n".join(
        f"- {p['name']}: R$ {p.get('unit_price', 'sob consulta')} — {p.get('description', '')}"
        for p in products
    ) or "Nenhum produto cadastrado."

    # Format qualification steps
    steps_text = "\n".join(
        f"{s['step_order']}. {s['question']}" + (" (obrigatória)" if s.get("is_required") else "")
        for s in steps
    ) or "Nenhum roteiro configurado."

    # Format FAQ
    faq_text = "\n".join(
        f"- Quando perguntarem sobre '{r['trigger_keyword']}': {r['response_text']}"
        for r in faq
    ) or "Nenhuma resposta rápida cadastrada."

    # Format forbidden topics
    forbidden_text = ", ".join(forbidden) if forbidden else "Nenhum tópico proibido."

    # Format company info
    if company:
        company_text = (
            f"Nome: {company.get('company_name', '')}\n"
            f"Segmento: {company.get('segment', '')}\n"
            f"Descrição: {company.get('description', '')}\n"
            f"Endereço: {company.get('address', '')}\n"
            f"Site: {company.get('website', '')}\n"
            f"Pagamento: {company.get('payment_methods', '')}\n"
            f"Diferenciais: {company.get('differentials', '')}"
        )
    else:
        company_text = "Dados da empresa não cadastrados."

    # Format history
    history_text = "\n".join(
        f"{'Lead' if h['role'] == 'user' else 'Você'}: {h['content']}"
        for h in history[-20:]  # Last 20 messages
    ) or "Primeira mensagem da conversa."

    # Format RAG
    rag_text = "\n".join(
        f"- {r['text']}" for r in rag_results
    ) or "Nenhum resultado na base de conhecimento."

    # Format scheduling (with live free slots if Google Calendar is connected)
    from app.skills.schedule import get_scheduling_context
    sched_text = await get_scheduling_context(org_id)

    # Replace placeholders
    prompt = template.format(
        agent_name=agent_config.get("agent_name", "Ana"),
        role="assistente de vendas" if agent_type == "sdr" else "assistente de suporte",
        personality=agent_config.get("personality", "Profissional, simpática e objetiva."),
        company_name=company.get("company_name", "a empresa") if company else "a empresa",
        forbidden_topics=forbidden_text,
        qualification_steps=steps_text,
        hot_criteria=hot_criteria or "Quando demonstrar interesse claro em comprar/agendar.",
        products_list=products_text,
        quick_responses=faq_text,
        rag_context=rag_text,
        company_info=company_text,
        scheduling_info=sched_text,
        conversation_history=history_text,
        contact_name=contact_name or "Não informado",
        contact_phone=contact_phone,
        deal_stage="Não identificado",
    )

    log.info(
        "Context built for %s agent (org=%s, conv=%s) — %d chars",
        agent_type, org_id, conversation_id, len(prompt),
    )
    return prompt
