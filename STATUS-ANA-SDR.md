# STATUS — Implementação Ana SDR (Lebedenco Agro)

> Documento vivo. Última atualização: **2026-05-04 21:00 BRT**
> Owner: Hugo Dower (Lords Ads)
> Cliente: Lebedenco Agro (Wagner / Luan)
> Agente AI: **Ana** (probióticos para nutrição animal)

---

## 🎯 Objetivo

Subir a **Ana** (SDR AI agent) atendendo a Lebedenco Agro via WhatsApp + Chatwoot, reusando o código `lords-ai` em modo multi-tenant. **Sem afetar a Aurora (LORDS).**

Arquitetura: **1 código (`lords-ai`), N deploys** — uma stack docker-compose por VPS de cliente, mesma imagem `ghcr.io/hugodower/lords-ai:latest`, `.env` distinto por org. Supabase compartilhado com isolamento via `organization_id` + RLS.

---

## ✅ FASE 1 — CONCLUÍDA (04/05/2026)

**Mudança técnica:** template per-org com fallback default em `app/guards/context_builder.py`.

| Item | Status | Commit / PR |
|---|---|---|
| PR #11 — `fix/aurora-org-lookup-vps-scope` | ✅ Merged | `8be6c47` |
| PR #12 — `feat/multi-template-routing` | ✅ Merged | `3e276fe` (inner: `4735af9`) |
| Template `templates/sdr_system_prompt_ana.md` | ✅ Committed | `8bb37b6` (324 linhas) |
| Deploy VPS LORDS via `python scripts/deploy.py` | ✅ Executado | service `lords-ai_app` updated 2026-05-04 20:55:57 BRT |
| Smoke test Aurora — resposta normal | ✅ | conv=287 e conv=288, tom Aurora preservado, memória funcionando, pipeline movendo |
| Log `[AI_AGENT] template selected (default): sdr_system_prompt.md` | ✅ Confirmado | linha 23:56:28 do log do Portainer |
| Zero regressão na Aurora | ✅ | confirmado |

**HEAD do main:** `8bb37b6c1109102428420bc939854cb5a2695c4e`

---

## 🔜 FASE 2 — Supabase SQLs (próximo passo)

Popular dados da Lebedenco no Supabase compartilhado.

### Pré-requisitos
- Acesso ao SQL Editor do Supabase (project `wdzpjfitmstyfbxwwgnv`)
- SQL preparado em `/mnt/user-data/outputs/lebedenco_ana_setup.sql` (já gerado em sessão anterior)

### Sequência
1. **Bloco 0 — Diagnóstico (read-only):** rodar primeiro pra validar nomes de colunas. Mandar resultado pro Claude validar.
2. **Bloco 1 — ALTER TABLE:** adicionar coluna `agent_configs.template_path TEXT NULL`.
3. **Bloco 2 — UPDATE Ana:** ativar `sdr` na org Lebedenco com `template_path='sdr_system_prompt_ana.md'`, personalidade definida, `closer` desativado.
4. **Bloco 3 — INSERT produtos:** 8 SKUs Lebedenco (Multiplicação 10kg/20kg, Probimais R, MultSacch, Bovnance pasta + kits 4/20/30un).
5. **Bloco 4 — INSERT label_mappings:** 6 stages (`01-novo-contato` → `06-negociacao`).
6. **Bloco 5 — VERIFY:** queries de validação pra conferir tudo antes de COMMIT.

### Identificadores Lebedenco
- **org_id:** `31ddcc20-868c-4988-9326-e15d7a27d06f`
- **Ana Chatwoot agent_id:** 5 (email `ana@ai.lebedenco.uk`)
- **Ana CRM user_id:** `a0000000-0000-0000-0000-000000000002`
- **Wagner CRM user_id:** `efc17797-b572-46ee-92b7-77670db0f026`
- **Luan CRM user_id:** `fc19abbc-1aab-4ada-8fdc-b6c5df98b6a3`
- **Chatwoot Lebedenco:** `chatw.lebedencoagro.uk`

---

## 🔜 FASE 3 — Deploy VPS Lebedenco

Provisionar `lords-ai` na VPS Lebedenco (`port.lebedencoagro.uk`).

### Sequência
1. Criar 6 labels em Chatwoot Lebedenco (`01-novo-contato` … `06-negociacao`)
2. Criar stack `lords-ai` no Portainer Lebedenco usando mesma imagem `ghcr.io/hugodower/lords-ai:latest`
3. Configurar `.env` com `ORG_ID=31ddcc20-868c-4988-9326-e15d7a27d06f`, credenciais Chatwoot/WhatsApp Lebedenco
4. Adicionar serviço **ChromaDB** na stack (paridade com LORDS, RAG)
5. Repointar webhook Chatwoot Lebedenco para o novo endpoint lords-ai (subdomain TBD — confirmar com Hugo: provável `ai.lebedencoagro.uk`)
6. Smoke test Ana via WhatsApp Lebedenco

### Pendência relacionada
- **Bug "John Doe" Lebedenco:** atual webhook do Chatwoot Lebedenco aponta pro lugar errado (`lordsads.com.br/api/webhooks/chatwoot-events` — LORDS CRM). Precisa repointar quando Ana for ao ar.

---

## 🐛 Bugs preexistentes mapeados (não bloqueiam Ana)

| Bug | Impacto | Bloqueia Ana? |
|---|---|---|
| `ChatwootClient.add_label` method missing | Aurora não consegue fazer handoff automático | ❌ Não — Ana faz handoff só por pedido explícito |
| `get_org_by_chatwoot_account` returns 204 | Fallback pra ORG_ID hardcoded; funciona por acaso na LORDS | ⚠️ Sim — vai falhar na Lebedenco se não corrigir antes da Fase 3 |
| Google Calendar `invalid_grant` | Aurora não agenda reuniões | ❌ Não — Ana não agenda reuniões (Lebedenco vende produto direto) |
| WhatsApp followup creds 204 | Followups falham silenciosamente | ❌ Não — separar do escopo Ana |

**Próxima janela pra resolver:** depois de Ana em produção, abrir PRs de fix.

---

## 📂 Arquivos relevantes do repo

| Arquivo | Propósito |
|---|---|
| `app/guards/context_builder.py` | `_load_template()` com suporte a `custom_path` |
| `app/services/supabase_client.py` | `agent_configs` SELECT * (puxa `template_path`) |
| `templates/sdr_system_prompt.md` | Template padrão (Aurora) |
| `templates/sdr_system_prompt_ana.md` | Template Ana (consultivo, sem agendamento, sem emoji) |
| `scripts/deploy.py` | Script de deploy via Portainer API |

---

## 🔧 Comandos úteis

```bash
# Trabalhar no projeto
cd D:/SaaS/lords-ai

# Status do deploy
git status
git log -5 --oneline

# Rodar testes (94 passaram em Fase 1)
pytest

# Deploy VPS LORDS
python scripts/deploy.py
```

### Portainer
- VPS LORDS: `portainer.lordsads.uk` → Services → `lords-ai_app`
- VPS Lebedenco: `port.lebedencoagro.uk` (lords-ai ainda não provisionado)

### Como validar deploy depois de mudança
1. Verificar **"Last updated at"** do service (deve ser recente)
2. Mandar mensagem pra Aurora no WhatsApp
3. No Portainer Logs, buscar (Ctrl+F): `template selected`
4. Linha esperada: `[AI_AGENT] template selected (default): sdr_system_prompt.md`

---

## 🚀 Como retomar

**No Claude Code (próximo terminal):**
> "Continuar implementação Ana SDR. Ler STATUS-ANA-SDR.md e me orientar próximo passo."

**No Claude (web/app):**
> "Bom dia, vamos retomar o projeto Ana SDR Lebedenco. Fechamos a Fase 1 ontem (deploy LORDS validado). Vamos seguir pra Fase 2 (SQLs Supabase)."

Eu busco o histórico desta conversa via search e a gente continua de onde parou.