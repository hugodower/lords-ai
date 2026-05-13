# Lebedenco Agro — Status Deploy Multi-tenant

## Atualização 07/mai/26 — Fase 2 (handoff bugs) APROVADA ✅

**Migration agent_configs.chatwoot_agent_email aplicada + 2 bugs corrigidos +
validados em produção.**

### Migration Supabase (manual via SQL Editor)
- `ALTER TABLE agent_configs ADD COLUMN chatwoot_agent_email TEXT`
- Ana populada: `chatwoot_agent_email='ana@ai.lebedenco.uk'`,
  `handoff_agent_id=3` (Luan Machado, user_id no Chatwoot Lebedenco)
- Aurora populada: `chatwoot_agent_email='aurora@ai.lordsads.uk'`
  (preservar comportamento via fallback hardcoded)
- Aurora `handoff_agent_id` mantido NULL (não tinha antes, decisão consciente)

### Bugs corrigidos (commit 6a02b71)
1. **Bug #1**: `get_active_agents()` em `app/integrations/supabase_client.py:59`
   agora seleciona `chatwoot_agent_email` e `handoff_agent_id` (antes faltavam
   no SELECT, causando fallback silencioso para Aurora email hardcoded)
2. **Bug #2**: `app/skills/handoff.py:90` agora usa
   `pipeline_manager.add_label_to_chatwoot()` (Opção A conservadora) em vez de
   `chatwoot_client.add_label()` que não existia (causava AttributeError em
   todos os handoffs, tanto Ana quanto Aurora)

### Validações em produção
- **Cenário 1 (auto-atribuição Ana)** ✅ — Conv #33: "Ana atribuiu a si
  mesmo essa conversa" + painel mostra "Agente atribuído: Ana"
- **Cenário 3 (handoff IA→humano)** ✅ — Conv #32: Ana detectou urgência
  médica + gerou resumo estruturado WARM + atribuiu Luan + label
  `01-novo-contato` aplicada

### User criado no Chatwoot Lebedenco
- Ana | id=5 | ana@ai.lebedenco.uk | role=Agente
- (Luan Machado já existia | id=3, Wagner | id=4, Admin | id=1)

### Pré-existente (dívida técnica não bloqueante)
- 7 testes em `tests/test_sdr.py` e `tests/test_support.py` falham por
  problemas de mock setup (não regressão da Fase 2 — confirmado via
  experimento `git checkout HEAD~1`). Eram ERRORs antes (AttributeError
  add_label), agora são FAILEDs por assertions de mock. Backlog separado.

## Pendências pós-Fase 2 (próximas sessões)

### Fase 3 — Pause per-conversation
Quando humano (Luan/Wagner) se atribui à conversa no Chatwoot, Ana deve parar
de responder. Quando humano desatribui (assignee=NULL) ou re-atribui pra Ana,
Ana deve voltar.
- Implementação proposta: Redis-based pause keyed por conversation_id
- Modificar `main.py:assignment_handler` (~linha 418-489) pra pausar/despausar
- Modificar `agents/base.py:process()` pra checar pause antes de responder
- Estimativa: ~2h

### Fase 4 — Progressão automática de etiquetas
Ana só aplica `01-novo-contato`, nunca avança para `02-diagnostico-da-dor`,
`03-protocolo-apresentado`, etc. Como labels Chatwoot ↔ stages do pipeline
LORDS CRM, isso trava o funil inteiro em "Novo Contato".
- Investigar lógica atual em `pipeline_manager.py`
- Definir critérios de progressão (sinais conversacionais → trigger advance)
- Implementar e testar
- Estimativa: ~2-3h

### Fase 5 — Calibração de gatilho de handoff
Ana faz handoff cedo demais (qualquer menção a urgência médica → escalation).
Refinar `sdr_system_prompt_ana.md` pra qualificar 2-3 perguntas antes de
escalar. Handoff só em: pedido explícito, sintomas extremos (mortalidade),
recusa de protocolo.
- Estimativa: ~1h

### Fase 6 — Follow-up reengajamento Lebedenco
Aproveitar janela 24h da Meta WhatsApp pra reengajar leads ociosos. Worker
de follow-up já existe (`app/services/followup_worker.py`) com cadência
24h/48h/7d, mas templates são genéricos/Aurora. Criar templates Meta
aprovados específicos pra Lebedenco (gado leiteiro), popular no Supabase.
- Estimativa: ~2-3h

### ✅ Bug "John Doe" — CORRIGIDO
Webhook configurado corretamente para `https://ai.lebedencoagro.uk/api/v1/webhook/chatwoot`.
Bug original era follow-up worker usando dados "congelados" (corrigido em 12/mai/26).

**Soluções implementadas:**
- Parser renomeado: `widget_form_parser.py` (semântica correta)
- Name resolution: Ana captura nome via conversa + atualiza Chatwoot
- Follow-up worker: temporariamente desligado (`FOLLOWUP_WORKER_ENABLED=false`)
- Diferenciação por canal: WhatsApp LP vs Site Widget vs Messenger DM

## Atualização 06/mai/26 — Etapa F APROVADA ✅

**Smoke test concluído com sucesso em 14:30 (06/mai/26).**

Hugo enviou mensagem teste do WhatsApp +5518996010895 → Chatwoot Lebedenco
conv #26 → Ana respondeu corretamente.

### Confirmações dos logs de produção
- Bug 4 RESOLVIDO: lookup `chatwoot account_id=1 → org=31ddcc20-...` funcionou
  perfeitamente (não cai mais no fallback hardcoded)
- Webhook → debounce → context builder → Claude API → resposta enviada
- Auto-label `01-novo-contato` aplicada corretamente
- Pipeline detectou lead em "Novo Contato" (position 1)
- Sandbox whitelist OK
- Channel detection OK (WhatsApp via Channel::Api)

### Última correção aplicada
- `CLAUDE_API_KEY` foi rotacionada novamente (a anterior estava retornando
  401 invalid x-api-key da Anthropic). Key nova validada via curl antes do deploy.

### Pendências pós-Etapa F (não bloqueantes pra produção, mas necessárias)
1. **Auto-atribuição da Ana ao Chatwoot** — não está acontecendo. Aurora
   (LORDS Ads) já tem isso (virtual user a0000000-0000-0000-0000-000000000001).
   Investigação em andamento.
2. **Handoff humano → Ana para de responder** — não implementado pra Ana
3. **Handoff Ana → humano** (sentiment/intent) — verificar se já existe
4. ~~**Bug "John Doe" persiste**~~ — ✅ **CORRIGIDO** (12/mai/26)

### Lebedenco Agro — Status Deploy (05/mai/26)

**Estado:** Etapas A-E concluídas. Etapa F (smoke test) pendente.

**Endpoints:**
- App: `https://ai.lebedencoagro.uk` (SSL Let's Encrypt OK)
- Health: `https://ai.lebedencoagro.uk/health` →
  `{"status":"ok","org_id":"31ddcc20-868c-4988-9326-e15d7a27d06f","agents_active":["sdr"],"redis":"connected","chroma":"connected"}`

**Infraestrutura:**
- VPS: Lebedenco (Portainer em `port.lebedencoagro.uk`)
- Stack name: `lords-ai`
- Image: `ghcr.io/hugodower/lords-ai:latest`
- Replicas: 1
- Network: `vps` (Traefik) + `lords-network` (interno)
- Serviços auxiliares: `lords-redis` (redis:7-alpine), `lords-chromadb` (chromadb/chroma:0.5.23)

**Configuração relevante:**
- `SANDBOX_MODE=true`
- `SANDBOX_PHONES`: +5518996010895, +5518981550333, +5518991023817
- `MAX_RESPONSE_TIME_SECONDS=10`
- `CHATWOOT_URL`: `https://chatw.lebedencoagro.uk`
- `CHATWOOT_ACCOUNT_ID`: 1
- `GOOGLE_CLIENT_ID/SECRET`: vazios (Calendar OAuth ainda não configurado)
- `CHATWOOT_WEBHOOK_SECRET`: NÃO configurado (lords-ai não valida HMAC)

**Webhooks Chatwoot Lebedenco (estado atual):**

| # | Nome | URL | Eventos |
|---|---|---|---|
| 1 | CRM LORDS | `https://www.lordsads.com.br/api/webhooks/chatwoot-events?token=...` | Todos |
| 2 | Ana - lords-ai (SDR) | `https://ai.lebedencoagro.uk/api/v1/webhook/chatwoot` | conversation_created, conversation_updated, message_created |

**Bugs corrigidos durante o deploy:**
1. `REDIS_URL` tinha trailing space (`redis://lords-redis:6379 `),
   causando "Port could not be cast to integer" e fallback para in-memory
2. `CLAUDE_API_KEY` estava com valor placeholder literal
   (`COLE_AQUI_A_KEY_NOVA_ROTACIONADA`) — substituída pela key real
3. `SUPABASE_SERVICE_KEY` estava inválida — rotacionada no Supabase Dashboard
   (chave antiga foi exposta inadvertidamente em ambiente de chat)

**Pendências conhecidas:**
- [ ] Etapa F: smoke test end-to-end (Ana respondendo no WhatsApp)
- [x] ~~Bug "John Doe" persiste~~ — ✅ **CORRIGIDO** (12/mai/26)
- [ ] Rotacionar `CHATWOOT_API_TOKEN` da Lebedenco (security debt)
- [ ] Configurar Google Calendar OAuth para Lebedenco (Item 3 lords-ai global)

**Configuração de Inboxes Lebedenco:**
| Inbox ID | Tipo | Descrição | Diferenciação Ana |
|----------|------|-----------|-------------------|
| 3 | Messenger (Meta Business Suite) | Facebook + Instagram unificados | DM direto → apresentação suave |
| 4 | WhatsApp Cloud API (+551832175059) | Leads das LPs + DMs orgânicos | LP → direto p/ qualificação |
| 5 | Site Widget | Widget embedado nas LPs | Form preenchido → direto p/ diagnóstico |

**Diferenças vs. deploy LORDS Ads (referência):**
- Org: Lebedenco usa nome "Ana" (config no Supabase via tabela `organization_agents`)
- Inboxes: 3 ativas (vs. 1 LORDS)
- Sandbox phones diferentes
- Follow-up worker: desligado (vs. ativo LORDS)