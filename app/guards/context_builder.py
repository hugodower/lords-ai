from __future__ import annotations

from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

from app.integrations import supabase_client as sb
from app.memory.redis_store import get_conversation_history, get_agreed_schedule
from app.knowledge.rag import search_knowledge
from app.utils.logger import get_logger

BRT = timezone(timedelta(hours=-3))

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
    contact_memory: Optional[dict] = None,
) -> str:
    """Build the full system prompt with verified data from Supabase."""

    template = _load_template(agent_type)

    # Fetch all org data from Supabase
    try:
        company = await sb.get_company_info(org_id)
    except Exception as exc:
        log.warning("Failed to load company_info: %s", exc)
        company = None
    try:
        products = await sb.get_products(org_id)
    except Exception as exc:
        log.warning("Failed to load products: %s", exc)
        products = []
    try:
        steps = await sb.get_qualification_steps(org_id, agent_type)
    except Exception as exc:
        log.warning("Failed to load qualification_steps: %s", exc)
        steps = []
    try:
        faq = await sb.get_quick_responses(org_id)
    except Exception as exc:
        log.warning("Failed to load quick_responses: %s", exc)
        faq = []
    try:
        forbidden = await sb.get_forbidden_topics(org_id)
    except Exception as exc:
        log.warning("Failed to load forbidden_topics: %s", exc)
        forbidden = []
    try:
        hot_criteria = await sb.get_hot_criteria(org_id)
    except Exception as exc:
        log.warning("Failed to load hot_criteria: %s", exc)
        hot_criteria = None
    # Conversation history from Redis
    try:
        history = await get_conversation_history(conversation_id)
    except Exception as exc:
        log.warning("Failed to load conversation history: %s", exc)
        history = []

    # RAG search for relevant knowledge
    try:
        rag_results = await search_knowledge(org_id, user_message, limit=3)
    except Exception as exc:
        log.warning("Failed RAG search: %s", exc)
        rag_results = []

    if not template:
        # Template file missing — build minimal prompt from Supabase data
        agent_name = agent_config.get("agent_name", "Ana")
        company_name = company.get("company_name", "a empresa") if company else "a empresa"
        personality = agent_config.get("personality", "Profissional, simpática e objetiva.")
        log.warning("Template not found for %s, using inline fallback", agent_type)
        return (
            f"Você é {agent_name}, assistente virtual da {company_name}. "
            f"{personality} "
            "Responda de forma curta, máximo 3 linhas, sem listas, tom informal. "
            "Nunca revele que é Claude ou IA."
        )

    # Format products list (DB column is 'unit_price')
    products_text = "\n".join(
        f"- {p['name']}: R$ {p.get('unit_price', 'sob consulta')} — {p.get('description', '')}"
        for p in products
    ) or "Nenhum produto cadastrado."

    # Format qualification steps
    steps_text = "\n".join(
        f"{s['step_order']}. {s['question']}"
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

    # Current datetime in BRT for the prompt
    DIAS_SEMANA = ["Segunda-feira", "Terça-feira", "Quarta-feira",
                   "Quinta-feira", "Sexta-feira", "Sábado", "Domingo"]
    now_brt = datetime.now(BRT)
    dia_semana = DIAS_SEMANA[now_brt.weekday()]
    current_datetime_text = (
        f"Hoje é {dia_semana}, {now_brt.strftime('%d/%m/%Y')} "
        f"às {now_brt.strftime('%H:%M')} (horário de Brasília - UTC-3).\n"
        f"Use essa data como referência para agendamentos. "
        f"O ano atual é {now_brt.year}."
    )

    # Fetch previously agreed schedule data from Redis
    agreed = await get_agreed_schedule(conversation_id)
    if agreed:
        parts = []
        if agreed.get("requested_date"):
            parts.append(f"Data combinada: {agreed['requested_date']}")
        if agreed.get("requested_time"):
            parts.append(f"Horário combinado: {agreed['requested_time']}")
        if agreed.get("attendee_name"):
            parts.append(f"Nome confirmado: {agreed['attendee_name']}")
        if agreed.get("attendee_email"):
            parts.append(f"Email confirmado: {agreed['attendee_email']}")
        if agreed.get("participant"):
            parts.append(f"Participante: {agreed['participant']}")
        if agreed.get("whatsapp_for_reminders"):
            parts.append(f"WhatsApp lembretes: {agreed['whatsapp_for_reminders']}")
        if agreed.get("interest"):
            parts.append(f"Interesse: {agreed['interest']}")
        agreed_text = (
            "DADOS JÁ COMBINADOS COM O LEAD (NÃO pergunte de novo!):\n"
            + "\n".join(f"  - {p}" for p in parts)
        )
        log.info("[CONTEXT] Agreed schedule found for conv=%s: %s", conversation_id, parts)
    else:
        agreed_text = ""

    # Replace placeholders
    prompt = template.format(
        current_datetime=current_datetime_text,
        agreed_schedule=agreed_text,
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

    # Inject long-term contact memory if available
    if contact_memory:
        from app.services.memory_manager import format_memory_for_prompt
        memory_text = format_memory_for_prompt(contact_memory)
        if memory_text:
            prompt += memory_text

    log.info(
        "Context built for %s agent (org=%s, conv=%s) — %d chars | "
        "agent_name=%s | company=%s | products=%d | steps=%d | faq=%d | "
        "forbidden=%d | history=%d msgs | rag=%d results | scheduling=%s | memory=%s",
        agent_type, org_id, conversation_id, len(prompt),
        agent_config.get("agent_name", "?"),
        (company.get("company_name") if company else "N/A"),
        len(products),
        len(steps),
        len(faq),
        len(forbidden),
        len(history),
        len(rag_results),
        "yes" if "google_calendar" in sched_text.lower() else "basic",
        "yes" if contact_memory else "no",
    )
    return prompt
