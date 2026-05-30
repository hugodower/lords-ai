from __future__ import annotations

from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

from app.integrations import supabase_client as sb
from app.memory.redis_store import get_conversation_history, get_agreed_schedule
from app.knowledge.rag import search_knowledge
from app.services.pipeline_manager import get_current_stage
from app.utils.logger import get_logger

BRT = timezone(timedelta(hours=-3))

log = get_logger("context_builder")


def _detect_inbox_origin(channel: str, conversation_meta: dict = None) -> str:
    """
    Detecta origem do lead baseado no canal e metadados.

    Returns:
        'lp_whatsapp': WhatsApp vindo das LPs (Inbox 4)
        'lp_widget': Site Widget vindo das LPs (Inbox 5)
        'meta_dm': DM direto do Messenger/Instagram (Inbox 3)
    """
    # Mapeamento baseado no brief - IDs das inboxes Lebedenco
    if channel == "WhatsApp":
        # Inbox 4: WhatsApp Cloud API (+551832175059)
        # Leads das LPs que clicam no botão wa.me
        return "lp_whatsapp"
    elif channel == "Site":
        # Inbox 5: Site Widget embedado nas LPs
        # Visitante anônimo com pre-chat form
        return "lp_widget"
    elif channel in ("Messenger", "Instagram"):
        # Inbox 3: Meta Business Suite (Messenger unificado)
        # DMs diretos sem contexto da LP
        return "meta_dm"
    else:
        # Email, Telegram, etc. - tratar como DM direto
        return "meta_dm"

TEMPLATES_DIR = Path(__file__).parent.parent.parent / "templates"


async def _get_deal_stage_for_context(org_id: str, contact_phone: str) -> str:
    """
    Helper para buscar o stage atual do deal para injetar no contexto da Aurora.

    Retorna o nome do stage (ex: "02. Qualificação") ou default para novos contatos.
    """
    try:
        current_stage = await get_current_stage(org_id, contact_phone)
        return current_stage["name"] if current_stage else "01. Novo Contato"
    except Exception as e:
        log.warning("[CONTEXT:STAGE] Erro ao buscar stage para %s: %s", contact_phone, str(e))
        return "01. Novo Contato"


def _load_template(agent_type: str, custom_path: Optional[str] = None) -> str:
    if custom_path:
        custom_template_path = TEMPLATES_DIR / custom_path
        if custom_template_path.exists():
            log.info("[AI_AGENT] template selected: %s", custom_template_path.name)
            return custom_template_path.read_text(encoding="utf-8")
        else:
            log.warning(
                "[AI_AGENT] custom template not found: %s, falling back to default",
                custom_template_path.name,
            )

    # Fallback to default template
    template_path = TEMPLATES_DIR / f"{agent_type}_system_prompt.md"
    log.info("[AI_AGENT] template selected (default): %s", template_path.name)
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
    sentiment_data: Optional[dict] = None,
    channel: str = "WhatsApp",
    campaign_context: Optional[dict] = None,
) -> str:
    """Build the full system prompt with verified data from Supabase."""

    template = _load_template(
        agent_type=agent_type,
        custom_path=agent_config.get("template_path"),
    )

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
    try:
        label_mappings = await sb.get_label_mappings(org_id)
    except Exception as exc:
        log.warning("Failed to load label_mappings: %s", exc)
        label_mappings = []
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
            "Não abra a conversa dizendo que é IA, mas se perguntarem diretamente, "
            "responda com transparência. Nunca mencione Claude, Anthropic ou OpenAI."
        )

    # Format products list — WITHOUT price (Aurora nunca menciona valores;
    # preço é decidido pós-agendamento de reunião)
    products_text = "\n".join(
        f"- {p['name']}: {p.get('description', '')}"
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

    # Format valid labels (stage labels da org — Aurora NUNCA deve inventar
    # label fora dessa lista)
    # Fonte de verdade dos labels: pipeline_stages.chatwoot_label da org
    org_labels = await sb.get_all_chatwoot_labels(org_id)
    if org_labels:
        valid_labels_text = "\n".join(f"- {label}" for label in org_labels)
    elif label_mappings:
        # Fallback legacy: usa label_mappings se pipeline_stages estiver vazio
        valid_labels_text = "\n".join(
            f"- {m['chatwoot_label']}" for m in label_mappings if m.get("chatwoot_label")
        )
    else:
        # Último fallback: só o stage de entrada (não-crash)
        log.warning("[CONTEXT_BUILDER] No labels found for org=%s — using minimum fallback", org_id)
        valid_labels_text = "- 01-novo-contato"

    # Format company info
    if company:
        company_text = (
            f"Nome: {company.get('company_name', '')}\n"
            f"Segmento: {company.get('segment', '')}\n"
            f"Descrição: {company.get('description', '')}\n"
            f"Endereço: {company.get('address', '')}\n"
            f"Site: {company.get('website', '')}\n"
            f"Pagamento: {company.get('payment_methods', '')}\n"
            f"Chave PIX: {company.get('pix_key', '')} (tipo: {company.get('pix_key_type', '')})\n"
            f"Beneficiário PIX: {company.get('pix_holder_name', '')}\n"
            f"Diferenciais: {company.get('differentials', '')}"
        )
    else:
        company_text = "Dados da empresa não cadastrados."

    # Format company description (for SDR template "Sobre a empresa" section)
    if company:
        company_name_val = company.get("company_name") or "a empresa"
        segment_val = company.get("segment") or ""
        description_val = company.get("description") or ""
        differentials_val = company.get("differentials") or ""
        company_desc_parts = []
        if description_val:
            company_desc_parts.append(description_val)
        elif segment_val:
            company_desc_parts.append(f"{company_name_val} é uma empresa especializada no segmento de {segment_val}.")
        else:
            company_desc_parts.append(f"{company_name_val}.")
        if differentials_val:
            company_desc_parts.append(f"\nDiferenciais: {differentials_val}")
        company_description = "\n".join(company_desc_parts)
    else:
        company_description = "Dados da empresa não cadastrados. Consulte a seção 'Dados da empresa' abaixo."

    # Format post-scheduling process
    DEFAULT_POST_SCHEDULING = (
        "1. Reunião de diagnóstico gratuita\n"
        "2. Proposta personalizada\n"
        "3. Implementação após aprovação\n"
        "4. Suporte dedicado"
    )
    post_scheduling_process = DEFAULT_POST_SCHEDULING
    if company and company.get("post_scheduling_process"):
        post_scheduling_process = company["post_scheduling_process"]

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

    # Log agent config keys for debugging
    log.info(f"[CONTEXT:KEYS] agent_cfg keys: {list(agent_config.keys())}")

    # Validate and extract agent config with safe defaults
    agent_name = agent_config.get("agent_name")
    if not agent_name:
        log.error(f"[CONTEXT:CONFIG] Missing agent_name in config for org={org_id} — this is a configuration error")
        agent_name = "Assistente"

    company_name = company.get("company_name", "a empresa") if company else "a empresa"
    personality = agent_config.get("personality", "Profissional, simpática e objetiva.")

    # Replace placeholders
    try:
        prompt = template.format(
            current_datetime=current_datetime_text,
            agreed_schedule=agreed_text,
            agent_name=agent_name,
            role="assistente de vendas" if agent_type == "sdr" else "assistente de suporte",
            personality=personality,
            company_name=company_name,
            company_description=company_description,
            post_scheduling_process=post_scheduling_process,
            forbidden_topics=forbidden_text,
            valid_labels=valid_labels_text,
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
            deal_stage=await _get_deal_stage_for_context(org_id, contact_phone),
            handoff_agent_name=agent_config.get("handoff_agent_name") or "nosso especialista",
        )
    except KeyError as e:
        template_path = agent_config.get("template_path", f"{agent_type}_system_prompt.md")
        log.error(f"[CONTEXT:MISSING_KEY] key={e} agent_cfg_keys={list(agent_config.keys())} template={template_path}")

        # Create robust fallback with identity and JSON contract
        log.warning(f"[CONTEXT:FALLBACK] Template format failed, creating fallback prompt with identity for org={org_id}")

        prompt = f"""Você é {agent_name}, assistente virtual da {company_name}.

## Sua personalidade
{personality}

## Instruções importantes
- Responda de forma curta, máximo 3 linhas, sem listas, tom informal.
- Não abra a conversa dizendo que é IA, mas se perguntarem diretamente, responda com transparência.
- Nunca mencione Claude, Anthropic ou OpenAI.
- Sempre mantenha o foco nos serviços da {company_name}.

## Produtos e serviços disponíveis
{products_text}

## Informações da empresa
{company_text}

## FORMATO DE RESPOSTA OBRIGATÓRIO

Sua resposta deve estar SEMPRE em formato JSON válido:

{{
  "text": "sua mensagem para o cliente",
  "action": "continue",
  "lead_temperature": "cold",
  "skill_used": "general",
  "summary": "resumo breve da conversa"
}}

## Histórico da conversa
{history_text}

## Dados do contato
Nome: {contact_name or "Não informado"}
Telefone: {contact_phone}

Data e hora atual: {current_datetime_text}"""

    # Guard de sanidade: verificar se prompt tem tamanho mínimo e identidade
    if len(prompt) < 200 or agent_name not in prompt:
        log.error(f"[CONTEXT:SANITY_FAIL] Generated prompt too short or missing identity for org={org_id}")
        # Último recurso: prompt mínimo absolutamente seguro
        prompt = f"""Você é {agent_name}, assistente virtual da {company_name}.

{personality}

Responda em formato JSON: {{"text": "mensagem", "action": "continue", "lead_temperature": "cold", "skill_used": "general"}}

Histórico: {history_text}
Contato: {contact_name or "Não informado"} ({contact_phone})"""

    # Detect origin and inject specific instructions
    inbox_origin = _detect_inbox_origin(channel)

    if inbox_origin == "lp_whatsapp":
        # Inbox 4: WhatsApp das LPs - produtor tem contexto
        prompt += """

## ORIGEM: LP WHATSAPP
O produtor já visitou nosso material da Lebedenco e preencheu o form com interesse específico.
ELE JÁ CONHECE A EMPRESA e nossos produtos.

**ABORDAGEM:** Pular apresentação institucional. Ir direto para:
- "Vi que você está interessado no nosso protocolo/suplemento para [gado de corte/leite]"
- Fazer perguntas de qualificação sobre o rebanho atual
- Diagnosticar necessidades específicas
- Apresentar protocolo adequado ao perfil

**TOM:** Consultivo, direto, especialista. O lead já está "aquecido"."""

    elif inbox_origin == "lp_widget":
        # Inbox 5: Site Widget das LPs - dados via pre-chat form
        prompt += """

## ORIGEM: LP WIDGET
O produtor preencheu pre-chat form no nosso site (gado-de-corte ou gado-de-leite).
ELE JÁ TEM INTERESSE ESPECÍFICO e visitou nosso conteúdo.

**ABORDAGEM:** Pular apresentação institucional. Focar em:
- Referenciar o material que ele estava vendo
- "Vi que você estava vendo nosso conteúdo sobre [protocolo/gado de corte/leite]"
- Qualificar necessidades específicas do rebanho
- Avançar para diagnóstico técnico

**TOM:** Especialista, consultivo, assumir interesse prévio."""

    elif inbox_origin == "meta_dm":
        # Inbox 3: DM direto - pode não ter contexto
        prompt += """

## ORIGEM: META DM
Produtor enviou DM direto pelo Facebook/Instagram. PODE NÃO TER CONTEXTO da Lebedenco.
Ele pode estar em descoberta inicial ou resposta a algum post/anúncio.

**ABORDAGEM:** Descobrir contexto primeiro:
- "Oi! Como posso te ajudar?"
- Se não mencionar Lebedenco/protocolo: apresentar brevemente a empresa
- "Aqui é a Ana da Lebedenco Agro, trabalhamos com protocolos nutricionais para gado"
- Então qualificar interesse e necessidades

**TOM:** Acolhedor, descobrir intenção, apresentação suave quando necessário."""

    # Add channel-specific technical instructions
    if channel != "WhatsApp":
        _channel_capture_instructions = {
            "Instagram": (
                "\n**CANAL INSTAGRAM:** Seja visual e dinâmica. Quando demonstrar interesse, "
                "peça WhatsApp: 'Pra te passar mais detalhes, qual seu WhatsApp? 😊'"
            ),
            "Messenger": (
                "\n**CANAL MESSENGER:** Tom amigável. Quando demonstrar interesse, "
                "peça WhatsApp: 'Pra continuar mais prático, me passa seu WhatsApp? 😊'"
            ),
            "Site": (
                "\n**CANAL SITE:** Visitante pode sair a qualquer momento. "
                "Capturar WhatsApp/email na 2ª mensagem: 'Pra não perder contato, "
                "me passa seu WhatsApp ou email? 😊'"
            ),
            "Email": (
                "\n**CANAL EMAIL:** Textos estruturados OK. "
                "Se fizer sentido, ofereça WhatsApp para respostas rápidas."
            ),
            "Telegram": (
                "\n**CANAL TELEGRAM:** Mensagens curtas. "
                "Se interessado, sugira WhatsApp para facilitar atendimento."
            ),
        }
        capture_text = _channel_capture_instructions.get(channel, (
            f"\n**CANAL {channel.upper()}:** Mantenha mensagens profissionais e objetivas."
        ))
        prompt += capture_text

    # Inject long-term contact memory if available
    if contact_memory:
        from app.services.memory_manager import format_memory_for_prompt
        memory_text = format_memory_for_prompt(contact_memory)
        if memory_text:
            prompt += memory_text

    # Inject campaign context if present and recent (< 72h)
    if campaign_context:
        try:
            received_at = campaign_context.get("received_at", "")
            is_recent = True
            if received_at:
                from datetime import datetime as _dt
                try:
                    ts = _dt.fromisoformat(received_at.replace("Z", "+00:00"))
                    age_hours = (datetime.now(timezone.utc) - ts).total_seconds() / 3600
                    is_recent = age_hours <= 72
                except (ValueError, TypeError):
                    pass

            if is_recent:
                ctype = campaign_context.get("type", "")
                parts = [
                    "\n\n## CONTEXTO DE CAMPANHA",
                    "Este contato chegou através de uma campanha. Adapte sua abordagem:",
                    "",
                ]
                if ctype == "ctwa_ad":
                    parts.append(f"Tipo: Anúncio Click-to-WhatsApp")
                    if campaign_context.get("headline"):
                        parts.append(f"Título do anúncio: \"{campaign_context['headline']}\"")
                    if campaign_context.get("body"):
                        parts.append(f"Texto do anúncio: \"{campaign_context['body']}\"")
                elif ctype == "template_response":
                    parts.append(f"Tipo: Resposta a template de disparo em massa")
                    if campaign_context.get("template_name"):
                        parts.append(f"Template: \"{campaign_context['template_name']}\"")
                    if campaign_context.get("template_body"):
                        parts.append(f"Mensagem do template: \"{campaign_context['template_body']}\"")
                elif ctype == "campaign_label":
                    labels = campaign_context.get("labels", [])
                    parts.append(f"Tipo: Campanha identificada por labels")
                    parts.append(f"Labels: {', '.join(labels)}")

                parts.extend([
                    "",
                    "IMPORTANTE:",
                    "- NÃO use saudação genérica. Referencie diretamente o tema da campanha/anúncio.",
                    "- Seja direta e conecte com o que a campanha prometeu.",
                    "- NÃO repita o texto inteiro da campanha, apenas referencie o tema.",
                ])
                prompt += "\n".join(parts)
                log.info("[CONTEXT] Campaign context injected: type=%s conv=%s", ctype, conversation_id)
        except Exception as camp_err:
            log.warning("[CONTEXT] Error injecting campaign context: %s", camp_err)

    # Inject sentiment-based tone adjustment
    sentiment_label = "neutral"
    if sentiment_data and sentiment_data.get("sentiment", "neutral") != "neutral":
        from app.services.sentiment_analyzer import format_sentiment_for_prompt
        sentiment_text = format_sentiment_for_prompt(sentiment_data)
        if sentiment_text:
            prompt += sentiment_text
        sentiment_label = sentiment_data.get("sentiment", "neutral")

    log.info(
        "Context built for %s agent (org=%s, conv=%s) — %d chars | "
        "agent_name=%s | company=%s | products=%d | steps=%d | faq=%d | "
        "forbidden=%d | labels=%d | history=%d msgs | rag=%d results | scheduling=%s | memory=%s | sentiment=%s | campaign=%s",
        agent_type, org_id, conversation_id, len(prompt),
        agent_config.get("agent_name", "?"),
        (company.get("company_name") if company else "N/A"),
        len(products),
        len(steps),
        len(faq),
        len(forbidden),
        len(label_mappings),
        len(history),
        len(rag_results),
        "yes" if "google_calendar" in sched_text.lower() else "basic",
        "yes" if contact_memory else "no",
        sentiment_label,
        campaign_context.get("type") if campaign_context else "no",
    )
    return prompt
