# Brief de implementação — lords-ai: migração de modelo + prompt caching

**Contexto do incidente:** o modelo `claude-sonnet-4-20250514` foi retirado da API da Anthropic em 15/06/2026. Toda chamada a ele retorna `404 not_found_error`, o que derrubou a geração da Ana (e provavelmente da Aurora, mesma base). Os logs mostram o pipeline 100% saudável até a chamada do Claude — só o model string está morto.

**Objetivo deste trabalho:**
1. Ressuscitar a Ana trocando o modelo retirado pelos atuais.
2. Centralizar o model string em env vars (blindar contra a próxima deprecation).
3. Separar geração (Sonnet 4.6) de classificação de intent (Haiku 4.5) pra cortar custo.
4. Implementar prompt caching no bloco estático de contexto (maior alavanca de custo).

> Sempre opção 1, sem auto-approve. Revisar todos os diffs antes de commitar.

---

## Passo 1 — Localizar os call sites

```bash
grep -rn "claude-sonnet-4-20250514" .
grep -rn "claude-sonnet-4" .
grep -rn "messages.create" .
grep -rn "anthropic" --include="*.py" -l .
```

Pelos logs, existem no mínimo dois pontos que chamam a API:
- **Geração principal** — módulo `agent:base` (a resposta da Ana).
- **Classificação de intent** — módulo `intent_classifier` / `claude`.

Confirmar se o model string está hardcoded em cada um ou se já há um ponto único. O `agent_config` carregado da DB **não** tem campo `model` (keys: `id, organization_id, agent_type, is_active, agent_name, personality, claude_api_key, max_messages, ...`), então é hardcode em código.

---

## Passo 2 — Centralizar o modelo em env vars

**`.env`** (e `.env.example`):

```env
# Modelos Claude — atualizar aqui quando houver deprecation
CLAUDE_MODEL_AGENT=claude-sonnet-4-6
CLAUDE_MODEL_INTENT=claude-haiku-4-5-20251001
```

**Módulo de settings/config** (onde já se lê o resto do ambiente):

```python
import os

CLAUDE_MODEL_AGENT = os.getenv("CLAUDE_MODEL_AGENT", "claude-sonnet-4-6")
CLAUDE_MODEL_INTENT = os.getenv("CLAUDE_MODEL_INTENT", "claude-haiku-4-5-20251001")
```

Models atuais e válidos (verificados na doc oficial em 17/06/2026):

| Uso | Model ID | Preço in/out (por 1M tokens) |
|---|---|---|
| Geração (Ana) | `claude-sonnet-4-6` | $3 / $15 |
| Intent classifier | `claude-haiku-4-5-20251001` | $1 / $5 |
| (overkill p/ SDR) Opus | `claude-opus-4-8` | $5 / $25 |

Observação de custo: `claude-sonnet-4-20250514` já era tier Sonnet ($3/$15), então a geração migra sem mudança de preço. A economia vem de mover o intent pra Haiku (3x mais barato) e do caching abaixo.

---

## Passo 3 — Apontar cada call site pra sua env var

**Geração (`agent:base`):**

```python
from config import CLAUDE_MODEL_AGENT

response = client.messages.create(
    model=CLAUDE_MODEL_AGENT,   # era "claude-sonnet-4-20250514"
    max_tokens=...,
    system=...,
    messages=...,
)
```

**Intent classifier:**

```python
from config import CLAUDE_MODEL_INTENT

response = client.messages.create(
    model=CLAUDE_MODEL_INTENT,  # era "claude-sonnet-4-20250514"
    max_tokens=...,
    messages=...,
)
```

> Adaptar à assinatura real das chamadas. Não inventar parâmetros — só trocar o valor de `model`.

Depois deste passo a Ana já volta a responder. Os passos de caching são otimização.

---

## Passo 4 — Prompt caching no contexto estático (a alavanca de custo)

**Por que importa aqui:** o log mostra contexto de **68.056 chars** (~17-20k tokens) por chamada de geração. A maior parte é estática (system prompt da Ana, company_info, 5 produtos, personality). Cache hit custa 10% do input normal — 90% de desconto.

### Pegadinha crítica — separar prefixo estático de sufixo dinâmico

O caching só vale pro **prefixo** do prompt, na ordem `tools → system → messages`, até o bloco marcado com `cache_control`. **Qualquer byte que mude antes do breakpoint invalida o cache.** Então:

- **Estático (cacheável, vai ANTES do breakpoint):** system prompt da Ana, company_info, produtos, personality, política comercial. Idêntico a cada turno e entre conversas da mesma org.
- **Dinâmico (NÃO cacheável, vai DEPOIS do breakpoint):** histórico da conversa, memória do lead, mensagem atual, sentiment, estágio do pipeline.

Se hoje o `context_builder` junta tudo (inclusive histórico) numa única string de system, o caching quase não ajuda — porque o histórico muda todo turno e invalida o prefixo. **A mudança estrutural é montar o system como lista de blocos, com o bloco estático separado e o breakpoint logo após ele.**

### Implementação (caching explícito)

```python
response = client.messages.create(
    model=CLAUDE_MODEL_AGENT,
    max_tokens=...,
    system=[
        {
            "type": "text",
            "text": STATIC_CONTEXT,   # system Ana + company_info + produtos + personality
            "cache_control": {"type": "ephemeral"},   # breakpoint AQUI
        },
        {
            "type": "text",
            "text": DYNAMIC_CONTEXT,  # memória, sentiment, estágio, etc. (sem cache_control)
        },
    ],
    messages=conversation_history,  # histórico + mensagem atual
)
```

Alternativa mais simples (caching automático): passar um único `cache_control` no nível raiz do request — o sistema coloca o breakpoint no último bloco cacheável sozinho. Começar por aqui se a refatoração do prefixo já estiver feita.

### Detalhes confirmados na doc

- Mínimo cacheável: **1.024 tokens p/ Sonnet** (seu bloco estático passa folgado). Para Haiku o mínimo é 4.096 — por isso não vale a pena cachear o intent classifier; deixa ele só no Haiku puro.
- TTL padrão: 5 min, **renovado a cada hit**. Numa operação 24/7 com tráfego constante, o bloco estático da org tende a ficar sempre quente.
- Custo de escrita do cache: 1,25x input (5 min). Leitura: 0,10x. Opção de TTL 1h existe (`"ttl": "1h"`, escrita 2x) — só considerar se houver janelas longas sem mensagens.
- Caching é GA em todos os modelos ativos — **não precisa de header beta**.

---

## Passo 5 — Build, deploy e validação

1. Rebuild da imagem e redeploy do serviço lords-ai no Portainer/Swarm.
2. Conferir que as env vars novas estão no stack/compose do serviço.
3. Mandar mensagem nova de um telefone sandbox (a "Oiii" da conv=175 já foi consumida como `action=error`, o debounce não reprocessa sozinho).
4. No log, confirmar que a geração completa em vez do `ERROR ... 404`. Esperado: o fluxo seguir após `[CONTEXT] Context built ...` sem o erro do Claude.
5. **Validar o caching:** inspecionar `response.usage` — em chamadas subsequentes da mesma conversa, `cache_read_input_tokens` deve ser > 0. Se vier sempre 0, o prefixo estático está sendo invalidado (algo dinâmico vazou pra antes do breakpoint).

---

## Passo 6 — Aurora (mesma base)

A Aurora roda na mesma lords-ai. Se compartilha os call sites, já é corrigida junto. Conferir o log dela depois do deploy e mandar uma mensagem de teste pra confirmar que também voltou.

---

## Checklist final

- [ ] `grep` mapeou todos os usos de `claude-sonnet-4-20250514`
- [ ] Env vars `CLAUDE_MODEL_AGENT` / `CLAUDE_MODEL_INTENT` criadas e lidas no config
- [ ] Geração aponta pra `CLAUDE_MODEL_AGENT` (Sonnet 4.6)
- [ ] Intent aponta pra `CLAUDE_MODEL_INTENT` (Haiku 4.5)
- [ ] Contexto separado em estático (cacheável) + dinâmico
- [ ] `cache_control` no bloco estático
- [ ] Env vars presentes no stack do Portainer/Swarm
- [ ] Deploy feito, teste sandbox respondido pela Ana
- [ ] `cache_read_input_tokens > 0` validado
- [ ] Aurora conferida
