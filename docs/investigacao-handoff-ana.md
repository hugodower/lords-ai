# Investigação: Auto-atribuição e Handoff Ana — 06/05/26

## TL;DR
- **Cenário 1 (Auto-atribuição)**: IMPLEMENTADO, mas COM BUG — `get_active_agents` não seleciona `chatwoot_agent_email`
- **Cenário 2 (Humano assume)**: PARCIAL — detecta mudança de assignee e atualiza CRM, mas não pausa bot
- **Cenário 3 (IA faz handoff)**: IMPLEMENTADO, mas COM BUG — chama método `add_label` inexistente
- **Sistema de pause global**: existe via API `/agents/pause`, mas não é per-conversation
- **Schema fields faltando**: Ana precisa de `chatwoot_agent_email` e `handoff_agent_id` configurados

## Cenário 1 — Auto-atribuição

### Estado atual
- ✅ **Código implementado**: `chatwoot.py:94-126` método `_auto_assign_ai_agent()`
- ✅ **Fluxo ativo**: chamado automaticamente após `send_message()` não-private (linha 169-176)
- ✅ **Lógica robusta**: verifica se conversa já tem assignee humano antes de atribuir
- 🐛 **BUG CRÍTICO**: `get_active_agents()` só seleciona `agent_type, agent_name, is_active` (supabase_client.py:59), mas `_get_ai_agent_email()` tenta acessar `chatwoot_agent_email` (chatwoot.py:55)
- ⚠️ **Fallback**: quando falha, usa `DEFAULT_AI_AGENT_EMAIL = "aurora@ai.lordsads.uk"` (linha 12)

### Gap pra Ana
1. Ana precisa do campo `chatwoot_agent_email` populado no Supabase
2. `get_active_agents()` precisa incluir esse campo no SELECT
3. Ana precisa de um usuário virtual correspondente no Chatwoot Lebedenco

### Implementação proposta
1. Corrigir `supabase_client.py:59` — adicionar `chatwoot_agent_email` no SELECT
2. Verificar/criar usuário virtual "Ana" no Chatwoot Lebedenco com email único
3. Atualizar registro Ana no Supabase com o email correto
4. Smoke test: enviar mensagem e verificar auto-atribuição no painel Chatwoot

## Cenário 2 — Humano assume

### Estado atual
- ✅ **Handler implementado**: `main.py:163-172` processa webhook `conversation_updated`
- ✅ **Detecção de assignee**: `main.py:418-489` captura mudanças em `assignee_id`
- ✅ **CRM sync**: atualiza `owner_user_id` do contato baseado no email do agente Chatwoot
- ❌ **GAP CRÍTICO**: não pausa o bot automaticamente — IA continua respondendo após humano se atribuir
- ✅ **Sistema pause global**: existe `is_paused()` controlado via `/api/v1/agents/pause`, mas é global, não per-conversation

### Gap pra Ana
- Falta lógica para pausar conversas específicas quando humano assume
- Sistema atual de pause é global (para todas conversas), não granular
- Necessário implementar pause per-conversation ou detecção contextual

### Implementação proposta
1. Criar `redis_store.py` função `pause_conversation(conv_id)` e `is_conversation_paused(conv_id)`
2. Modificar `main.py:assignment_handler` para pausar conv quando humano se atribui
3. Modificar `agents/base.py:process()` para checar pause per-conversation antes de responder
4. Adicionar endpoint `/resume-conversation/{conv_id}` para humano reativar bot

## Cenário 3 — Ana faz handoff

### Estado atual
- ✅ **Skill implementado**: `skills/handoff.py:53-115` função `perform_handoff()` completa
- ✅ **Resumo estruturado**: gera nota privada com histórico, temperatura do lead, motivo
- ✅ **Atribuição humana**: usa `handoff_agent_id` da config do agente
- ✅ **RAG + cleanup**: salva conversa no knowledge base e limpa estado Redis
- 🐛 **BUG**: linha 90 chama `chatwoot_client.add_label(conversation_id, "handoff-ia")` mas método não existe
- ✅ **Alternativa funcional**: existe `pipeline_manager.py:352` `add_label_to_chatwoot()` que faz a mesma coisa

### Gap pra Ana
- Corrigir chamada de `add_label` inexistente
- Configurar `handoff_agent_id` para Ana (ID do agente humano Lebedenco no Chatwoot)

### Implementação proposta
1. Substituir `chatwoot_client.add_label()` por `add_label_to_chatwoot()` em `handoff.py:90`
2. Configurar `handoff_agent_id` no registro Ana (Supabase) com ID do Luan/Wagner
3. Testar handoff completo: trigger → resumo → atribuição → label → pause

## Schema Supabase relevante

### agent_configs (colunas confirmadas via código)
- ✅ `organization_id, agent_type, agent_name, is_active` — selecionados em queries
- ✅ `personality, sandbox_mode, handoff_agent_id` — acessados via `get_agent_config()`
- ❌ `chatwoot_agent_email` — usado no código mas não selecionado em `get_active_agents()`
- ❓ Outros campos: `max_messages, claude_api_key, template_path` (referenciados na doc)

### Comparação Aurora vs Ana
**Aurora (org LORDS Ads cc000000-...):**
- `chatwoot_agent_email`: provavelmente `aurora@ai.lordsads.uk`
- `handoff_agent_id`: configurado (auto-handoff funciona)

**Ana (org Lebedenco 31ddcc20-...):**
- `chatwoot_agent_email`: ❌ NULL ou vazio (por isso fallback para Aurora email)
- `handoff_agent_id`: ❓ desconhecido

### Conversas (campos inferidos)
- `meta.assignee` ou `assignee` — usado para detectar agente atribuído
- `meta.sender.id` — Chatwoot contact ID para linking CRM

## ChatwootClient

### Métodos existentes
```python
# Autenticação e config
__init__(), _resolve_config(), _url()

# Auto-atribuição
_get_ai_agent_email(), _get_ai_agent_id(), _auto_assign_ai_agent()

# Messaging
send_message(), send_private_note()

# Atribuição manual
assign_agent()

# Contacts
get_contact_info(), update_contact()
```

### Métodos faltando
- ❌ `add_label()` — chamado no handoff.py mas não existe
- ⚠️ **Workaround**: usar `pipeline_manager.add_label_to_chatwoot()`
- ❓ `remove_label()` — pode ser necessário para cleanup
- ❓ `get_conversation()` — pode ser útil para status checks

## Riscos identificados

### Produção LORDS Ads
- ✅ **Baixo risco**: mudanças propostas são aditivas ou correções de bugs
- ✅ **Aurora protegida**: usa email hardcoded como fallback, continuará funcionando
- ⚠️ **Teste necessário**: verificar se correção do `get_active_agents()` não quebra Aurora

### Migrações de schema
- ❌ **Nenhuma migration necessária**: campos já existem, só falta populá-los
- ✅ **Update simples**: apenas UPDATE Ana com `chatwoot_agent_email` e `handoff_agent_id`

### Breaking changes potenciais
- ❌ **Nenhum**: todas as mudanças são backward-compatible
- ✅ **Graceful fallback**: sistema já lida com campos ausentes

## Plano de implementação consolidado

### Fase 1 — Correções críticas (30min)
1. **Fix auto-atribuição**: Corrigir `supabase_client.py:get_active_agents()` SELECT
2. **Fix handoff label**: Substituir `add_label()` por `add_label_to_chatwoot()` em handoff.py

### Fase 2 — Configuração Ana (45min)
3. **Usuário virtual Lebedenco**: Criar "Ana" no Chatwoot com email único
4. **Config Ana**: UPDATE Supabase com `chatwoot_agent_email` e `handoff_agent_id`
5. **Smoke test auto-assign**: Verificar Ana se atribui corretamente

### Fase 3 — Pause per-conversation (2h)
6. **Redis functions**: Implementar `pause_conversation()` e `is_conversation_paused()`
7. **Assignment handler**: Pausar conv quando humano se atribui
8. **Agent process guard**: Checar pause antes de responder
9. **Resume endpoint**: API para reativar bot numa conversa

### Fase 4 — Validação end-to-end (1h)
10. **Smoke test completo**: Auto-assign → humano assume → pause → resume → handoff
11. **Logs monitoring**: Verificar comportamento em ambiente Lebedenco
12. **Rollback plan**: Procedimento caso algo quebre

## Esforço estimado
- **Total**: 4 horas
- **Fase 1** (correções): 30min
- **Fase 2** (config Ana): 45min
- **Fase 3** (pause granular): 2h
- **Fase 4** (validação): 45min

## Perguntas em aberto
1. **Email Ana**: Qual email usar para usuário virtual Ana? Sugestão: `ana@ai.lebedencoagro.uk`
2. **Handoff agent**: Qual ID do Luan/Wagner no Chatwoot Lebedenco para handoff?
3. **Pause behavior**: Quando humano resume conversa, bot deve voltar automaticamente ou aguardar comando?
4. **Priority**: Implementar pause per-conversation ou aceitar comportamento atual (humano manda bot parar via mensagem)?
5. **Rollback**: Manter mudanças em feature flag até validação completa?