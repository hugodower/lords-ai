# Relatório de Auditoria — Migração de Labels LORDS

## Resumo
- **Total de ocorrências encontradas**: 47
- **Categoria A (crítico)**: 4 arquivos, 10 linhas críticas
- **Categoria B (docs)**: 2 arquivos, 3 linhas
- **Categoria C (scripts/tests)**: 4 arquivos, 34 linhas

## Categoria A — Lógica de runtime (CRÍTICO)

### Arquivo: app/services/pipeline_manager.py
| Linha | Valor antigo | Contexto | Sugestão |
|-------|--------------|----------|----------|
| 22-25 | `STAGE_LABELS = {"novo_lead", "qualificado", "reuniao_agendada", "enviar_proposta", "em_negociacao", "fechou", "perdeu"}` | Definição de constante usada em validação/remoção | **CRÍTICO**: Substituir por labels numéricos |
| 284 | `l in STAGE_LABELS` | Lógica de remoção de labels antigos | Dependente da correção da constante |
| 285 | `l not in STAGE_LABELS` | Lógica de preservação de labels não-stage | Dependente da correção da constante |
| 441 | `stage_label not in STAGE_LABELS` | Validação de stage válido | Dependente da correção da constante |
| 488 | `"novo_lead"` | `await swap_chatwoot_label(org_id, conversation_id, "novo_lead")` | Trocar por `"01-novo-contato"` |

### Arquivo: app/agents/base.py
| Linha | Valor antigo | Contexto | Sugestão |
|-------|--------------|----------|----------|
| 287 | `"em_negociacao"` | `await update_stage(..., "em_negociacao", ...)` | Trocar por `"05-em-negociacao"` |
| 614 | `"reuniao_agendada"` | `await update_stage(..., "reuniao_agendada", ...)` | Trocar por `"03-reuniao-agendada"` |
| 616 | `"reuniao_agendada"` | `schedule_resolve(org_id, conversation_id, 30, "reuniao_agendada")` | Trocar por `"03-reuniao-agendada"` |
| 618 | `"em_negociacao"` | `await update_stage(..., "em_negociacao", ...)` | Trocar por `"05-em-negociacao"` |
| 621 | `"qualificado"` | `await update_stage(..., "qualificado", ...)` | Trocar por `"02-qualificacao"` |

### Arquivo: app/services/followup_worker.py
| Linha | Valor antigo | Contexto | Sugestão |
|-------|--------------|----------|----------|
| 111 | `"perdeu"` | `await update_stage(org_id, contact_phone, str(conv_id), "perdeu", contact_name)` | **ATENÇÃO**: Label removida, substituir por status `lost` na API |

### Arquivo: app/services/conversation_resolver.py
| Linha | Valor antigo | Contexto | Sugestão |
|-------|--------------|----------|----------|
| 18 | `"reuniao_agendada"` | `REASONS = {"reuniao_agendada": "Reuniao agendada..."}` | Trocar key por `"03-reuniao-agendada"` |

## Categoria B — Docs e comentários

### Arquivo: app/services/pipeline_manager.py
| Linha | Valor antigo | Contexto | Sugestão |
|-------|--------------|----------|----------|
| 476 | `novo_lead` | `"""Ensure contact+deal exist. Adds novo_lead label only for new deals."""` | Atualizar docstring para `01-novo-contato` |
| 489 | `novo_lead` | `log.info("[PIPELINE] First contact — novo_lead label set for conv %s", conversation_id)` | Atualizar log para `01-novo-contato` |

### Arquivo: RELATORIO_ARQUITETURA_AGENTES.md
| Linha | Valor antigo | Contexto | Sugestão |
|-------|--------------|----------|----------|
| 342 | `qualificados` | `dados qualificados` (contexto descritivo) | Manter (não é label, é português comum) |

## Categoria C — Scripts e fixtures

### Arquivo: scripts/backfill_chatwoot_novo_lead.py
| Linha | Valor antigo | Contexto | Sugestão |
|-------|--------------|----------|----------|
| 34 | `LABEL = "novo_lead"` | Constante do script | Script específico para label antigo — **DEPRECAR** ou adaptar |
| 2,5,8,9,125,etc | Múltiplas | Docstring, help text, prints | Se manter script, atualizar docs |

### Arquivo: scripts/fix_chatwoot_novo_lead.py
| Linha | Valor antigo | Contexte | Sugestão |
|-------|--------------|----------|----------|
| 34,37,38-45 | `LABEL = "novo_lead"` + `STAGE_LABELS` | Constantes e validação | Script específico — **DEPRECAR** ou adaptar |

### Arquivo: scripts/rename_chatwoot_label.py
| Linha | Valor antigo | Contexto | Sugestão |
|-------|--------------|----------|----------|
| 131 | `proposta_enviada` | Argumento default | Script genérico — OK, são exemplos |
| 134 | `enviar_proposta` | Argumento default | Script genérico — OK, são exemplos |

### Arquivo: scripts/seed_knowledge_base.py
| Linha | Valor antigo | Contexto | Sugestão |
|-------|--------------|----------|----------|
| 47 | `qualificados` | `leads qualificados` em exemplo | Manter (contexto descritivo) |

## Observações e riscos

### Risco 1 — Array de constantes STAGE_LABELS
**CRÍTICO**: O array `STAGE_LABELS` em `pipeline_manager.py` linha 22-25 é usado para:
- **Validação** (linha 441): Rejeita stages que não estão no array
- **Lógica de swap** (linhas 284-285): Remove labels "stage" antigos antes de adicionar novo

**Impacto**: Se mudar apenas este array sem coordenar com o CRM, pode haver:
- Labels órfãos no Chatwoot (antigos não removidos)
- Rejeição de stages válidos
- **Recomendação**: Atualizar array + testar remoção de labels antigos

### Risco 2 — Labels removidas (fechou/perdeu)
**CRÍTICO**: `followup_worker.py` linha 111 ainda usa `"perdeu"` que foi removido.
- **Impacto**: Timeout automático vai falhar ao tentar aplicar label inexistente
- **Recomendação**: Substituir por call para atualizar status do deal para `lost`

### Risco 3 — Scripts em produção
**MODERADO**: Scripts `backfill_chatwoot_novo_lead.py` e `fix_chatwoot_novo_lead.py` podem estar rodando em produção.
- **Impacto**: Podem reverter labels novas para antigas
- **Recomendação**: Verificar crontabs e deprecar scripts antigos

### Risco 4 — Backward compatibility
**MODERADO**: Se Aurora já processa conversas com labels antigas em produção:
- **Cenário**: Conversa tem label `qualificado` (antigo) → Aurora tenta `update_stage("qualificado")` → Webhook novo rejeita
- **Recomendação**: Período de dual-read (aceitar ambos nomes) por 7-14 dias durante migração

### Risco 5 — Teste end-to-end
**CRÍTICO**: Pipeline completo precisa ser testado:
1. Aurora chama `update_stage("02-qualificacao")`
2. Webhook LORDS aplica label no Chatwoot
3. CRM move deal para stage correspondente
4. Sync bidirecional funciona

## Priorização de correções

### Fase 1 — Crítico (não pode deploar sem isso)
1. **pipeline_manager.py** linha 22-25: Atualizar `STAGE_LABELS`
2. **base.py** linhas 287,614,616,618,621: Todos os `update_stage()` hardcoded
3. **followup_worker.py** linha 111: Corrigir `"perdeu"` → status API
4. **conversation_resolver.py** linha 18: Atualizar key do `REASONS`

### Fase 2 — Logs e docs
5. **pipeline_manager.py** linhas 476,489: Docstring e logs
6. Scripts deprecation ou adaptação

### Fase 3 — Testes
7. Criar casos de teste para novos labels
8. Smoke test do pipeline end-to-end

---

## ✅ FASE 2 — Correções aplicadas

**Branch**: `fix/labels-migration-lords`
**Data**: 2026-04-24

### Alterações
- `pipeline_manager.py`: STAGE_LABELS atualizado, swap_chatwoot_label corrigido, +2 funções (mark_deal_as_lost, mark_deal_as_won)
- `agents/base.py`: 5 strings de stage atualizadas
- `followup_worker.py`: substituído update_stage("perdeu") por mark_deal_as_lost()
- `conversation_resolver.py`: key REASONS atualizada
- `scripts/`: removidos backfill_chatwoot_novo_lead.py e fix_chatwoot_novo_lead.py

### Sanity check
- ✅ Grep exaustivo retornou 0 ocorrências de labels antigos em app/

### Pendente
- [ ] PR review
- [ ] Smoke test em staging
- [ ] Merge + deploy
- [ ] Validação end-to-end (criar conversa nova, ver card no estágio correto)