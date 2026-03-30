# Relatorio de Arquitetura — Lords AI Agents

> Data: 2026-03-29 | Versao: 1.0

---

## Sumario

1. [Nome do Agente — Hardcoded vs Dinamico](#1-nome-do-agente--hardcoded-vs-dinamico)
2. [O que e Configuravel por Organizacao Hoje](#2-o-que-e-configuravel-por-organizacao-hoje)
3. [Mudancas Necessarias para Multi-Org com Nomes Diferentes](#3-mudancas-necessarias-para-multi-org-com-nomes-diferentes)
4. [Status dos 3 Agentes Planejados](#4-status-dos-3-agentes-planejados)
5. [Conflitos ao Replicar para Outra Organizacao](#5-conflitos-ao-replicar-para-outra-organizacao)
6. [Roadmap para Multi-Org em Producao](#6-roadmap-para-multi-org-em-producao)

---

## 1. Nome do Agente — Hardcoded vs Dinamico

### Mecanismo dinamico (funciona corretamente)

O nome do agente e **configuravel por organizacao** via tabela `agent_configs`, coluna `agent_name` (default: `'Ana'`).

O fluxo de injecao funciona assim:

```
agent_configs.agent_name
    --> context_builder.py lê agent_config.get("agent_name", "Ana")
        --> template.format(agent_name=...)
            --> {agent_name} substituido no prompt
```

Ambos os templates (`sdr_system_prompt.md` e `support_system_prompt.md`) usam `{agent_name}` corretamente em todas as referencias ao nome do agente — saudacoes, regras de identidade, exemplos de fala.

### Referencias hardcoded "Aurora" (PROBLEMAS)

| Arquivo | Linha | Codigo | Impacto |
|---------|-------|--------|---------|
| `app/services/followup_worker.py` | 24 | `"Oi {name}! Aqui é a Aurora, da LORDS"` | **CRITICO** — mensagem enviada ao lead no follow-up de 7 dias. Cliente de outra org recebe "Aurora" independente do nome configurado. |
| `app/services/conversation_resolver.py` | 22 | `"Atendimento finalizado pela Aurora."` | **MEDIO** — nota privada no Chatwoot (visivel para agentes humanos, nao para o lead). |
| `app/services/conversation_resolver.py` | 70 | `"Conversa resolvida automaticamente pela Aurora"` | **MEDIO** — idem, nota privada. |
| `app/integrations/chatwoot.py` | 12 | `AURORA_EMAIL = "aurora@ai.lordsads.uk"` | **ALTO** — email usado para auto-assign no Chatwoot. Todas as orgs tentam atribuir conversas ao mesmo usuario virtual "Aurora". Se outra org nao tem esse agente, o auto-assign falha silenciosamente. |
| `app/integrations/chatwoot.py` | 47-105 | `_get_aurora_agent_id()`, `_auto_assign_aurora()` | **ALTO** — funcoes inteiras nomeadas "aurora", buscam agente por email fixo. |
| `scripts/seed_knowledge_base.py` | 65, 196-198, 351 | `"IA Aurora (SDR Automatizado)"`, `"A Aurora NUNCA deve..."` | **ALTO** — knowledge base inteira menciona "Aurora" por nome. Se seed for reusado para outra org, RAG retorna documentos com nome errado. |
| `scripts/create_ai_agent_users.sql` | Varias | `full_name = 'Aurora'`, `email = 'aurora@ai.lordsads.uk'` | **MEDIO** — cria usuario virtual com nome fixo. |

### Resumo

O **system prompt e 100% dinamico** — o nome do agente vem do banco e e injetado via placeholder. Porem, **6 pontos no codigo de servicos e integracao estao hardcoded "Aurora"**, sendo 2 com impacto direto no usuario final (follow-up 7d e knowledge base).

---

## 2. O que e Configuravel por Organizacao Hoje

Toda tabela de configuracao tem FK `organization_id`. O sistema ja e multi-tenant no schema.

### Tabelas de configuracao per-org

| Tabela | O que controla | Campos principais |
|--------|---------------|-------------------|
| `agent_configs` | Identidade e comportamento do agente | `agent_name`, `personality`, `agent_type`, `is_active`, `max_messages`, `handoff_agent_id`, `handoff_agent_name`, `claude_api_key` (override per-org) |
| `qualification_steps` | Roteiro de qualificacao (SDR) | `step_order`, `question`, `is_required`, por `agent_type` |
| `lead_hot_criteria` | Criterio para transferir ao humano | `criteria_description` (texto livre) |
| `business_hours` | Horario de funcionamento | `day_of_week`, `is_open`, `open_time`, `close_time` |
| `business_hours_config` | Comportamento fora do horario | `after_hours_message`, `after_hours_behavior` (reply_and_stop / reply_and_qualify / silent) |
| `quick_responses` | Respostas rapidas (FAQ) | `trigger_keyword`, `response_text` |
| `forbidden_topics` | Topicos proibidos | `topic` |
| `company_info` | Dados da empresa | `company_name`, `segment`, `description`, `address`, `website`, `payment_methods`, `differentials` |
| `scheduling_config` | Agendamento | `scheduling_type`, `google_calendar_id`, `google_oauth_token`, `slot_duration`, `buffer`, etc. |
| `followup_config` | Toggle de follow-ups | `enable_24h`, `enable_48h`, `enable_7d`, `enable_confirmacao`, `enable_lembrete` |
| `chatwoot_connections` | Credenciais Chatwoot + WhatsApp | `base_url`, `account_id`, `api_token`, `phone_number_id`, `access_token`, etc. |
| `products` | Catalogo de produtos | `name`, `unit_price`, `description` |

### Resolucao em runtime

```
Webhook Chatwoot chega
  --> payload.account.id
    --> supabase_client.get_org_by_chatwoot_account(account_id)
      --> org_id resolvido
        --> TODAS as queries subsequentes filtram por org_id
```

Se org_id nao e encontrado, cai no fallback `settings.org_id` (variavel de ambiente).

### O que NAO e configuravel por org hoje

| Item | Onde esta | Problema |
|------|-----------|----------|
| Email do agente virtual no Chatwoot | `chatwoot.py:12` hardcoded | Todas as orgs usam `aurora@ai.lordsads.uk` |
| Mensagem de follow-up 7 dias (Chatwoot direct) | `followup_worker.py:24` hardcoded | Nome "Aurora" fixo |
| Mensagens de resolucao automatica | `conversation_resolver.py:22,70` hardcoded | Nome "Aurora" fixo |
| Knowledge base (ChromaDB seed) | `seed_knowledge_base.py` hardcoded | Docs mencionam "Aurora" e servicos Lords Ads |
| Template do system prompt SDR | `templates/sdr_system_prompt.md` | Secao "Sobre a Lords Ads" com produtos/precos hardcoded |
| Modelo Claude e parametros | `claude_client.py` | Modelo (Sonnet), temperature (0.3), max_tokens (500) fixos globalmente |

---

## 3. Mudancas Necessarias para Multi-Org com Nomes Diferentes

### Prioridade 1 — Criticas (bloqueia deploy para segunda org)

#### 3.1 Dinamizar o nome do agente nos servicos

**followup_worker.py** — A mensagem de follow-up 7d precisa consultar `agent_configs.agent_name` para a org:

```python
# ANTES (hardcoded):
"7d": "Oi {name}! Aqui é a Aurora, da LORDS ..."

# DEPOIS (dinamico):
# Buscar agent_name da org antes de montar a mensagem
agent_config = await sb.get_agent_config(org_id)
agent_name = agent_config.get("agent_name", "Ana")
company = await sb.get_company_info(org_id)
company_name = company.get("company_name", "a empresa")
message = f"Oi {contact_name}! Aqui é a {agent_name}, da {company_name} ..."
```

**conversation_resolver.py** — Notas privadas devem usar nome dinamico:

```python
agent_config = await sb.get_agent_config(org_id)
agent_name = agent_config.get("agent_name", "Ana")
note = f"Conversa resolvida automaticamente pela {agent_name}."
```

#### 3.2 Dinamizar auto-assign no Chatwoot

**chatwoot.py** — O email do agente virtual precisa vir da configuracao per-org:

```python
# ANTES:
AURORA_EMAIL = "aurora@ai.lordsads.uk"

# DEPOIS:
# Novo campo em agent_configs ou chatwoot_connections:
#   chatwoot_agent_email VARCHAR(255)
# Buscar email do agente por org_id
```

Cada org precisara de um usuario virtual proprio no Chatwoot com email unico.

#### 3.3 Remover conteudo hardcoded do template SDR

O template `sdr_system_prompt.md` tem um bloco inteiro "Sobre a Lords Ads" com produtos e precos especificos. Isso precisa ser movido para `company_info` ou um novo campo `company_description_extended`.

### Prioridade 2 — Importantes (degradam a experiencia)

#### 3.4 Knowledge base per-org

O seed `scripts/seed_knowledge_base.py` esta hardcoded para a org LORDS com documentos que mencionam "Aurora". Precisa:
- Tornar o script parametrizado por org_id
- Remover referencias a "Aurora" dos documentos (usar "{agent_name}" ou termos genericos)
- Criar endpoint de upload de knowledge base per-org (ja existe `/api/v1/knowledge/upload` mas usa `settings.org_id` fixo)

#### 3.5 Criar script de provisionamento per-org

Criar um script/endpoint que provisione todos os recursos necessarios para uma nova org:
- Registro em `agent_configs`, `business_hours`, `company_info`, etc.
- Usuario virtual no Chatwoot
- Collection no ChromaDB

### Prioridade 3 — Nice-to-have

#### 3.6 Parametros do modelo por org

Permitir override de modelo Claude, temperature e max_tokens por org via `agent_configs`.

#### 3.7 Templates de prompt por org

Permitir que orgs tenham templates de system prompt customizados (armazenados no banco em vez de arquivos).

---

## 4. Status dos 3 Agentes Planejados

### 4.1 SDR (originalmente "Aurora") — IMPLEMENTADO

**Status: Producao**

O agente SDR e o core do sistema. Classe: `SDRAgent(BaseAgent)` em `app/agents/sdr.py`.

**Funcionalidades implementadas:**

| Feature | Status | Detalhes |
|---------|--------|----------|
| System prompt completo | OK | `templates/sdr_system_prompt.md` — 222 linhas, fluxo de vendas em 7 etapas |
| Qualificacao de leads | OK | Steps configuráveis por org via `qualification_steps` |
| Agendamento Google Calendar | OK | Integracao completa: busca slots, cria evento, envia confirmacao |
| Pipeline CRM | OK | Cria contato + deal, atualiza stage, swap de labels no Chatwoot |
| Follow-ups automaticos | OK | 24h, 48h, 7d + confirmacao + lembrete de reuniao |
| Knowledge base (RAG) | OK | ChromaDB per-org, busca semantica nos prompts |
| Memoria de contato | OK | Extracao via Haiku apos 5+ mensagens, 90 dias de validade |
| Analise de sentimento | OK | Keywords + fallback Haiku, handoff em frustração persistente |
| Saudacao inteligente | OK | Primeiro contato vs retorno, por canal, campanha-aware |
| Contexto de campanha | OK | CTWA ads, template responses, campaign labels |
| Multi-canal | OK | WhatsApp, Instagram, Messenger, Site, Email, Telegram |
| Debounce | OK | Buffer de 4s para mensagens rapidas |
| Rate limiting | OK | 30/min por telefone, 5 identicas = bloqueio |
| Intent classification | OK | Raiva, ameaca, medico, legal -> handoff imediato |
| Response validation | OK | Precos, promessas, topicos proibidos, tom, tamanho |
| Autonomy limit | OK | Max mensagens, timeout, detecao de loop |
| Sandbox mode | OK | So responde para telefones na whitelist |
| After-hours | OK | 3 modos: reply_and_stop, reply_and_qualify, silent |
| Handoff para humano | OK | Resumo completo + atribuicao no Chatwoot |
| Logs de conversa | OK | Audit trail completo em `ai_conversation_logs` |

### 4.2 Suporte — IMPLEMENTADO (basico)

**Status: MVP em producao**

Classe: `SupportAgent(BaseAgent)` em `app/agents/support.py`.

**Funcionalidades implementadas:**

| Feature | Status | Detalhes |
|---------|--------|----------|
| System prompt | OK | `templates/support_system_prompt.md` — mais simples que SDR |
| FAQ/Knowledge base | OK | Responde baseado no RAG e quick_responses |
| Handoff | OK | Apos 3 tentativas sem resolver, transfere |
| Pipeline CRM | OK | Herda toda a logica do BaseAgent |
| Multi-canal | OK | Herda do BaseAgent |
| Todos os guards | OK | Rate limit, intent, validation, autonomy — herdados |

**O que NAO tem (comparado ao SDR):**

| Feature | Status |
|---------|--------|
| Qualificacao de leads | N/A — nao e o proposito |
| Agendamento | N/A — nao agenda reunioes |
| Follow-ups proativos | Nao implementado |
| Fluxo de vendas | N/A |

**Nota:** SDR e Support sao subclasses "thin" do mesmo `BaseAgent`. A unica diferenca real e o `agent_type` que determina qual template de prompt e carregado. Toda a pipeline de 7 layers e identica.

### 4.3 Closer / Retencao — NAO IMPLEMENTADO

**Status: Apenas definido no schema**

| Item | Existe? | Detalhes |
|------|---------|----------|
| CHECK constraint no banco | SIM | `agent_type IN ('sdr', 'support', 'closer', 'retention')` |
| Classe Python | NAO | Nenhum `CloserAgent` ou `RetentionAgent` |
| Template de prompt | NAO | Nao existe `closer_system_prompt.md` nem `retention_system_prompt.md` |
| Registro em `AGENTS` (main.py) | NAO | So `{"sdr": ..., "support": ...}` |
| Logica especifica | NAO | Nenhuma diferenciacao de comportamento |

**Para implementar, seria necessario:**

1. Criar `app/agents/closer.py` e `app/agents/retention.py` (classes thin como SDR/Support)
2. Criar `templates/closer_system_prompt.md` e `templates/retention_system_prompt.md`
3. Registrar em `AGENTS` no `main.py`
4. Definir logica de selecao de agente (quando usar Closer vs SDR vs Support)
5. Skills especificas: negociacao para Closer, pesquisa de satisfacao para Retencao

---

## 5. Conflitos ao Replicar para Outra Organizacao Hoje

### 5.1 Conflitos CRITICOS (sistema quebra ou comportamento errado)

| # | Conflito | Impacto | Severidade |
|---|----------|---------|------------|
| 1 | **Follow-up 7d diz "Aurora"** | Lead da nova org recebe mensagem com nome errado | CRITICO |
| 2 | **Auto-assign busca `aurora@ai.lordsads.uk`** | Se o Chatwoot da nova org nao tem esse usuario, auto-assign falha silenciosamente. Conversas ficam sem responsavel. | ALTO |
| 3 | **Knowledge base hardcoded** | Se rodar `seed_knowledge_base.py`, insere docs da Lords Ads na collection da nova org. RAG retorna informacoes de outra empresa. | ALTO |
| 4 | **Template SDR com conteudo Lords Ads** | Secao "Sobre a Lords Ads" com produtos/precos aparece no prompt de TODA org que usar agente SDR. A IA vai vender Central de Multiatendimento por R$1.997 mesmo para uma clinica odontologica. | CRITICO |

### 5.2 Conflitos MEDIOS (degradam a experiencia)

| # | Conflito | Impacto |
|---|----------|---------|
| 5 | **Notas privadas dizem "Aurora"** | Agentes humanos da nova org veem "resolvida pela Aurora" sem saber quem e |
| 6 | **`settings.org_id` como fallback** | Se resolver org_id falhar, mensagens da nova org sao processadas como se fossem da org default |
| 7 | **ChromaDB collection naming** | Funciona (`org_{uuid}`), mas nao ha script de provisionamento — precisa seed manual |
| 8 | **Sandbox phones global** | `sandbox_phones` e env var global, nao per-org. Em sandbox mode, so telefones listados globalmente recebem resposta |

### 5.3 Conflitos BAIXOS (funcionais mas inconvenientes)

| # | Conflito | Impacto |
|---|----------|---------|
| 9 | **Deploy unico** | Uma unica instancia FastAPI atende todas as orgs. Se cair, todas param. |
| 10 | **Redis compartilhado** | Conversation history e debounce sao por conversation_id (Chatwoot), entao sao naturalmente isolados. Sem conflito real. |
| 11 | **Metricas e logs globais** | Endpoints `/api/v1/metrics` e `/api/v1/logs` usam `settings.org_id` fixo. Nao mostram dados de outras orgs. |

---

## 6. Roadmap para Multi-Org em Producao

### Fase 1 — Remover hardcodes (1-2 dias)

**Objetivo:** Permitir que uma segunda org use o sistema sem ver "Aurora" ou informacoes da Lords Ads.

| # | Tarefa | Arquivo | Esforco |
|---|--------|---------|---------|
| 1.1 | Dinamizar mensagem de follow-up 7d | `followup_worker.py:21-25` | 30min |
| 1.2 | Dinamizar notas de resolucao | `conversation_resolver.py:22,70` | 30min |
| 1.3 | Parametrizar email do agente virtual | `chatwoot.py:12` + novo campo em `agent_configs` ou `chatwoot_connections` | 1h |
| 1.4 | Renomear funcoes `_aurora_*` para `_ai_agent_*` | `chatwoot.py:47-105` | 30min |
| 1.5 | Extrair conteudo Lords Ads do template SDR para `company_info` / `products` | `templates/sdr_system_prompt.md:8-33` | 2h |
| 1.6 | Limpar seed de knowledge base (remover "Aurora", parametrizar org) | `scripts/seed_knowledge_base.py` | 1h |

**Entregavel:** Sistema funciona para segunda org com nome e conteudo proprio.

### Fase 2 — Provisionamento automatizado (2-3 dias)

**Objetivo:** Criar/configurar uma nova org com um unico comando ou endpoint.

| # | Tarefa | Detalhes |
|---|--------|---------|
| 2.1 | Script `provision_org.py` | Cria registros em todas as 12 tabelas de configuracao com defaults sensiveis |
| 2.2 | Criar usuario virtual no Chatwoot por org | Endpoint que cria agente com email `ai@{org_slug}.lordsads.uk` |
| 2.3 | Provisionar ChromaDB collection | Criar collection vazia + endpoint de upload de knowledge base per-org |
| 2.4 | Corrigir endpoints de metricas/logs | Aceitar `org_id` como query param (hoje usa `settings.org_id` fixo) |
| 2.5 | Sandbox mode per-org | Mover `sandbox_phones` para `agent_configs` (campo ja existe no schema!) |

**Entregavel:** `python scripts/provision_org.py --org-id=xxx --agent-name="Sofia" --company="Clinica XYZ"` cria tudo.

### Fase 3 — Template de prompt por org (3-5 dias)

**Objetivo:** Permitir que cada org tenha seu proprio prompt sem modificar arquivos.

| # | Tarefa | Detalhes |
|---|--------|---------|
| 3.1 | Novo campo `system_prompt_override TEXT` em `agent_configs` | Se presente, usa em vez do arquivo de template |
| 3.2 | Separar template generico vs conteudo da empresa | Template base com placeholders universais, conteudo especifico vem inteiro do banco |
| 3.3 | UI de edicao de prompt no frontend | Pagina em `configuracoes-org.html` para editar personalidade, fluxo, regras |
| 3.4 | Versionamento de prompts | Tabela `prompt_versions` para historico de mudancas |

### Fase 4 — Agentes Closer e Retencao (5-7 dias)

**Objetivo:** Implementar os 2 agentes planejados.

| # | Tarefa | Detalhes |
|---|--------|---------|
| 4.1 | Definir fluxo do Closer | Mapeamento de etapas: apresentacao de proposta, negociacao, fechamento |
| 4.2 | Template `closer_system_prompt.md` | Prompt com foco em conversao, objecoes, urgencia |
| 4.3 | Definir fluxo de Retencao | Pesquisa NPS, win-back, upsell |
| 4.4 | Template `retention_system_prompt.md` | Prompt com foco em satisfacao, renovacao, cross-sell |
| 4.5 | Logica de routing entre agentes | Regras: novo lead -> SDR, pos-venda -> Support, deal em negociacao -> Closer, cliente em risco -> Retencao |
| 4.6 | Transicao de contexto entre agentes | Quando SDR transfere para Closer, passar resumo + dados qualificados |

### Fase 5 — Producao multi-tenant robusta (5-7 dias)

**Objetivo:** Operacao confiavel com 10+ orgs.

| # | Tarefa | Detalhes |
|---|--------|---------|
| 5.1 | Rate limiting per-org | Limites de API Claude por org (custo) |
| 5.2 | Dashboard multi-org | Metricas consolidadas + drill-down por org |
| 5.3 | Health check per-org | Endpoint que verifica Chatwoot + ChromaDB + Calendar por org |
| 5.4 | Billing/usage tracking | Contagem de tokens e mensagens por org para faturamento |
| 5.5 | Seguranca: `.env` fora do git | Remover `.env` do repositorio, usar secrets manager |
| 5.6 | Escalabilidade horizontal | Multiplas replicas do FastAPI atras de load balancer |
| 5.7 | Monitoramento e alertas | Sentry/Datadog para erros, latencia, SLA |

---

## Apendice A — Arquitetura Atual (Visao Geral)

```
                    Chatwoot (per-org)
                         |
                    POST /webhook/chatwoot
                         |
                    [FastAPI - main.py]
                         |
              +----------+----------+
              |                     |
         resolve org_id        extract campaign
         from account_id       context (CTWA/template)
              |                     |
              +----------+----------+
                         |
                    [Debounce 4s]
                         |
                    [Select Agent]
                    SDR | Support
                         |
               [BaseAgent.process()]
                         |
         +---+---+---+---+---+---+---+
         |   |   |   |   |   |   |   |
        Biz Rate Intent Cancel Senti- Context Claude
        Hrs Limit Class  Fups  ment   Build   API
                                       |
                              +--------+--------+
                              |        |        |
                           Template  Supabase  ChromaDB
                           (.md)     (per-org)  (RAG)
                                       |
                              +--------+--------+
                              |        |        |
                           Validate  Autonomy  Response
                           Response  Limit     to Chatwoot
                              |
                     [Pipeline Manager]
                     [Memory Manager]
                     [Follow-up Scheduler]
```

## Apendice B — Stack Tecnologico

| Componente | Tecnologia | Versao |
|-----------|------------|--------|
| Backend | FastAPI + Uvicorn | Python 3.12 |
| LLM | Claude Sonnet (respostas) + Haiku (extracao) | Anthropic API |
| Banco de dados | Supabase (PostgreSQL) | - |
| Cache/State | Redis 7 Alpine | 128MB |
| Vector DB | ChromaDB | 0.5.23 |
| Calendario | Google Calendar API | OAuth2 |
| Messaging | Chatwoot + Meta Cloud API | - |
| Deploy | Docker Swarm + Portainer | - |
| CI/CD | GitHub Actions -> GHCR | - |
| Testes | Pytest (29 unit + 1 integration) | - |

## Apendice C — Decisao de Prioridade

**Para onboarding da segunda organizacao, o minimo viavel e a Fase 1** (1-2 dias de trabalho). Isso remove todos os hardcodes criticos e permite que outra org opere com nome e conteudo proprios.

A Fase 2 torna o processo repetivel. Sem ela, cada nova org exige configuracao manual de 12 tabelas + Chatwoot + ChromaDB.

As Fases 3-5 sao melhorias incrementais que podem ser feitas enquanto o sistema ja opera com multiplas orgs.
