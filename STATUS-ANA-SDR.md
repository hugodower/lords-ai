# STATUS — Implementação Ana SDR (Lebedenco Agro)

> Documento vivo. Última atualização: **2026-05-05 22:00 BRT**
> Owner: Hugo Dower (Lords Ads)
> Cliente: Lebedenco Agro (Wagner / Luan)
> Agente AI: **Ana** (probióticos para nutrição animal)

---

## 🎯 Objetivo

Subir a **Ana** (SDR AI agent) atendendo a Lebedenco Agro via WhatsApp + Chatwoot, reusando o código `lords-ai` em modo multi-tenant. **Sem afetar a Aurora (LORDS).**

Arquitetura: **1 código (`lords-ai`), N deploys** — uma stack docker-compose por VPS de cliente, mesma imagem `ghcr.io/hugodower/lords-ai:latest`, `.env` distinto por org. Supabase compartilhado com isolamento via `organization_id` + RLS.

---

## ✅ FASE 1 — CONCLUÍDA (04/05/2026)

Código `lords-ai` modificado e deployado na VPS LORDS. Aurora validada.

| Item | Status | Commit / PR |
|---|---|---|
| PR #11 — `fix/aurora-org-lookup-vps-scope` | ✅ Merged | `8be6c47` |
| PR #12 — `feat/multi-template-routing` | ✅ Merged | `3e276fe` (inner: `4735af9`) |
| Template `templates/sdr_system_prompt_ana.md` | ✅ Committed | `8bb37b6` (324 linhas) |
| Deploy VPS LORDS via `python scripts/deploy.py` | ✅ Executado | service `lords-ai_app` updated 2026-05-04 20:55:57 BRT |
| Smoke test Aurora — resposta normal | ✅ | conv=287 e conv=288, tom Aurora preservado, memória funcionando, pipeline movendo |
| Log `[AI_AGENT] template selected (default): sdr_system_prompt.md` | ✅ Confirmado | linha 23:56:28 do log do Portainer |
| Zero regressão na Aurora | ✅ | Confirmado |

---

## ✅ FASE 2 — CONCLUÍDA (05/05/2026)

Dados da Ana populados no Supabase compartilhado.

### Blocos executados

| Bloco | Resultado | Detalhe |
|---|---|---|
| 1 — ALTER TABLE `template_path` | ✅ | Coluna `TEXT NULL` adicionada em `agent_configs` |
| 2 — UPDATE Ana | ✅ | `is_active=true`, `template_path='sdr_system_prompt_ana.md'`, personality estendida com regras de tom técnico-comercial sem emojis |
| 3 — INSERT 5 produtos novos | ✅ | Catálogo Lebedenco com preços do Luan |
| 6 — Cleanup catálogo | ✅ | DELETE dos 9 produtos antigos sem `code` (preços abril) |
| Bloco 4 (label_mappings) | ⏭️ Não foi necessário | Mappings já estavam corretos no banco — confusão de tabela inicial (FK era pra `contact_labels`, não `pipeline_stages`) |
| 5 — VERIFY final | ✅ | Todos os contadores bateram (5/6/6/6/true/`sdr_system_prompt_ana.md`) |

### Pós-Fase 2 — Ajuste do template

| Item | Commit |
|---|---|
| Slug `02-diagnostico-dor` → `02-diagnostico-da-dor` (alinhar com Chatwoot/banco) | `2f88d6c` |

### Snapshot do estado Lebedenco no Supabase

**Identifiers:**
- org_id: `31ddcc20-868c-4988-9326-e15d7a27d06f`
- pipeline_id: `4524cc48-5312-4ba1-b8dd-9b069d1415b0` (nome: "Venda Consultiva Agro")
- agent_config Ana (sdr): `is_active=true`, `template_path='sdr_system_prompt_ana.md'`

**Catálogo (5 SKUs ativos):**

| Code | Nome | Preço | Unidade |
|---|---|---|---|
| LEB-BOV-80 | Bovnance 80g | R$ 63,27 | un |
| LEB-MULT-10 | Multiplicação 10kg | R$ 283,40 | kg |
| LEB-MULT-20 | Multiplicação 20kg | R$ 540,40 | kg |
| LEB-PROB-20 | Probimais R 20kg | R$ 1.249,80 | kg |
| LEB-MSAC-20 | MultSacch 20kg | R$ 1.455,80 | kg |

**Pipeline stages "Venda Consultiva Agro" (já existiam):**

| Pos | Nome | UUID |
|---|---|---|
| 1 | Novo Contato | `0f2a6023-6218-4d1e-acec-3d2aded96124` |
| 2 | Diagnóstico da Dor | `c6eec709-5b81-4505-a613-05842e462721` |
| 3 | Protocolo Apresentado | `8a3b8d9c-5814-4841-88c2-30978cfec7e4` |
| 4 | Qualificação | `5192df9f-4f17-44a4-b6a0-6ca56e5d461d` |
| 5 | Orçamento | `9acad273-33cd-4bcc-88e9-44e10e3b36fd` |
| 6 | Negociação | `a4f344f2-bc76-4bca-9136-7205730ecc2d` |

**Label mappings (Chatwoot ↔ Contact Labels CRM, todos auto_sync=true):**

| chatwoot_label | contact_label_id |
|---|---|
| 01-novo-contato | `cd1428a3-e837-4ae1-9412-7dc59b34f77a` |
| 02-diagnostico-da-dor | `39ccd58f-a919-4cbb-97ba-58cad2db69a4` |
| 03-protocolo-apresentado | `8938173c-8836-4f0e-a5e7-d456e61543d1` |
| 04-qualificacao | `c91ed72c-4ab5-49a4-bc83-18435592df0b` |
| 05-orcamento | `ea02ced8-b0c1-432e-bc36-e2836ac7e257` |
| 06-negociacao | `ba289106-43f2-4a25-a7ad-b572d6158e2e` |

> ⚠️ **Distinção importante descoberta na Fase 2:** `label_mappings.crm_label_id` é FK para `contact_labels`, **não** para `pipeline_stages`. As stages do Kanban (pipeline_stages) e os labels do CRM (contact_labels) são tabelas distintas — o sistema mapeia ambas separadamente quando a Ana retorna `stage` no JSON.

---

## 🔜 PENDÊNCIAS PRÉ-FASE 3 (não bloqueiam, mas resolver antes da Ana ir ao ar)

### 1. Políticas comerciais no contexto da Ana
Adicionar em `company_info` ou no template Ana:
- Descontos por volume Bovnance: 4un R$60,11/un | 8un R$56,94/un | 20un R$53,78/un | 30un R$51,25/un
- 5% adicional à vista (regra geral Lebedenco)
- Frete grátis: Multiplicação >= 60kg | Probimais R / MultSacch >= 40kg
- Até 10% de desconto na primeira compra

### 2. Bug 4 — `get_org_by_chatwoot_account` retorna 204
Atualmente o lords-ai cai num fallback hardcoded para o ORG_ID configurado no `.env`. Isso funciona "por acaso" na VPS LORDS porque ORG_ID=cc000000 bate com o webhook do Chatwoot Lords. **Vai falhar na Lebedenco** se a busca por `chatwoot_account_id=1` (Lebedenco também usa account_id=1 no seu Chatwoot próprio) cair no fallback errado. Precisa fix antes da Fase 3.

### 3. Documentação interna
Documentar `pipeline_ana.md` com regras de transição entre stages (já decididas, mas não materializadas).

---

## 🔜 FASE 3 — Deploy VPS Lebedenco

Provisionar `lords-ai` na VPS Lebedenco (`port.lebedencoagro.uk`).

### Sequência
1. Criar 6 labels em Chatwoot Lebedenco (mesmos slugs: `01-novo-contato` … `06-negociacao`)
2. Criar stack `lords-ai` no Portainer Lebedenco usando mesma imagem `ghcr.io/hugodower/lords-ai:latest`
3. Configurar `.env` com `ORG_ID=31ddcc20-868c-4988-9326-e15d7a27d06f`, credenciais Chatwoot/WhatsApp Lebedenco
4. Adicionar serviço **ChromaDB** na stack (paridade com LORDS, RAG)
5. Repointar webhook Chatwoot Lebedenco para o novo endpoint lords-ai (subdomain TBD — provável `ai.lebedencoagro.uk`)
6. Smoke test Ana via WhatsApp Lebedenco

### Pendência Lebedenco
- **Webhook configurado:** Chatwoot Lebedenco agora aponta corretamente para `https://ai.lebedencoagro.uk/api/v1/webhook/chatwoot`
- **Follow-up automático:** Temporariamente **desligado** via `FOLLOWUP_WORKER_ENABLED=false` em produção. Será redesenhado como follow-up estratégico em sprint futura

---

## 🐛 Bugs preexistentes mapeados

| Bug | Impacto | Status |
|---|---|---|
| `ChatwootClient.add_label` method missing | Aurora não consegue fazer handoff automático | ❌ Não bloqueia Ana (handoff só por pedido explícito) |
| ~~Bug "John Doe" followup congelado~~ | ~~Follow-ups com nome placeholder~~ | ✅ **CORRIGIDO** — Parser renomeado + name resolution + follow-up worker desabilitado |
| `get_org_by_chatwoot_account` returns 204 | Fallback pra ORG_ID hardcoded; funciona por acaso na LORDS | ⚠️ **Pendente** — vai falhar na Lebedenco se não corrigir |
| Google Calendar `invalid_grant` | Aurora não agenda reuniões | ❌ Não bloqueia Ana (venda produto direto) |
| WhatsApp followup creds 204 | Followups falham silenciosamente | ❌ Não bloqueia Ana (follow-up desligado) |

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

# Rodar testes
pytest

# Deploy VPS LORDS
python scripts/deploy.py
```

### Portainer
- VPS LORDS: `portainer.lordsads.uk` → Services → `lords-ai_app`
- VPS Lebedenco: `port.lebedencoagro.uk` (lords-ai ainda não provisionado — Fase 3)

### Como validar deploy depois de mudança no lords-ai
1. Verificar **"Last updated at"** do service no Portainer (deve ser recente)
2. Mandar mensagem pra Aurora/Ana no WhatsApp
3. No Portainer Logs, buscar (Ctrl+F): `template selected`
4. Linha esperada (LORDS): `[AI_AGENT] template selected (default): sdr_system_prompt.md`
5. Linha esperada (Lebedenco, depois da Fase 3): `[AI_AGENT] template selected: sdr_system_prompt_ana.md`

---

## 🚀 Como retomar

**No Claude Code (próximo terminal):**
> "Continuar implementação Ana SDR. Ler STATUS-ANA-SDR.md e me orientar próximo passo."

**No Claude (web/app):**
> "Bom dia, vamos retomar o projeto Ana SDR Lebedenco. Fechamos Fases 1 e 2. Vamos pra Fase 3 (deploy VPS Lebedenco) ou resolver pendências pré-Fase 3 (políticas comerciais + Bug 4)."

Eu busco o histórico dessa conversa via search e a gente continua de onde parou.