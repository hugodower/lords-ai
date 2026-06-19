-- Migration: per-org model/params em agent_configs (Fase 1b — multi-provider)
-- Data: 2026-06-19
-- Autor: Claude (feat/per-org-model-config)
--
-- BACKGROUND:
-- Hoje modelo e params do LLM são globais: model vem de settings.claude_model_agent
-- ("claude-sonnet-4-6"), e temperature/max_tokens estão hardcoded no call site da
-- geração (app/agents/base.py → generate_response: temperature=0.3, max_tokens=500).
-- Não há override per-org.
--
-- OBJETIVO:
-- Adicionar 4 colunas em agent_configs para permitir override per-org de provider,
-- modelo e parâmetros. TODAS com DEFAULT NULL.
--
-- INVARIANTE CRÍTICO (é o que torna seguro aplicar isto sozinho):
-- Com as colunas NULL, a resolução em runtime deve ser "valor da org → senão
-- default do código". NULL = nada muda. Toda org existente (Ana inclusa) fica
-- byte-idêntica — mesmo provider (anthropic), mesmo model (claude-sonnet-4-6),
-- mesma temperature (0.3), mesmo max_tokens (500) — até alguém setar um valor
-- de propósito.
--
-- ESCOPO: SÓ modelo/params. NÃO toca em resolução de claude_api_key per-org nem
-- em credenciais de provider (isso é Fase 4).
--
-- APLICAÇÃO: manual, no Supabase SQL Editor. NÃO aplicar via CLI nem service key.
-- Idempotente (ADD COLUMN IF NOT EXISTS) — pode rodar mais de uma vez sem efeito.
--
-- NOMENCLATURA: temperature/max_tokens foram namespaced com prefixo `model_` de
-- propósito, porque agent_configs já tem `max_messages` (limite de autonomia,
-- coisa diferente). `model_max_tokens` desambigua. `model_temperature` segue o
-- mesmo padrão. `llm_provider`/`model` ficam sem prefixo redundante.

BEGIN;

-- ── 1. Diagnóstico ANTES: quais das 4 colunas já existem? ──────────────────
-- (NOTICEs aparecem na aba "Messages" do SQL Editor; não altera nada.)
DO $$
DECLARE
  col TEXT;
  exists_count INT;
BEGIN
  RAISE NOTICE '── Diagnóstico pré-migration (agent_configs) ──';
  FOREACH col IN ARRAY ARRAY['llm_provider', 'model', 'model_temperature', 'model_max_tokens']
  LOOP
    SELECT COUNT(*) INTO exists_count
    FROM information_schema.columns
    WHERE table_schema = 'public'
      AND table_name = 'agent_configs'
      AND column_name = col;

    IF exists_count > 0 THEN
      RAISE NOTICE 'coluna "%": JÁ EXISTE (ADD será no-op)', col;
    ELSE
      RAISE NOTICE 'coluna "%": ausente (será criada)', col;
    END IF;
  END LOOP;
END $$;

-- ── 2. Adicionar as 4 colunas (todas DEFAULT NULL, nenhuma NOT NULL) ───────
-- ADD COLUMN sem DEFAULT cravado e nullable é instantâneo (não reescreve a tabela).
ALTER TABLE agent_configs
  ADD COLUMN IF NOT EXISTS llm_provider      TEXT,           -- ex: 'anthropic'; NULL → default do código
  ADD COLUMN IF NOT EXISTS model             TEXT,           -- ex: 'claude-sonnet-4-6'; NULL → settings.claude_model_agent
  ADD COLUMN IF NOT EXISTS model_temperature NUMERIC(3,2),   -- ex: 0.30; NULL → default do código (0.3)
  ADD COLUMN IF NOT EXISTS model_max_tokens  INT;            -- ex: 500; NULL → default do código (500)

COMMENT ON COLUMN agent_configs.llm_provider      IS 'Override per-org do provider LLM (ex: anthropic). NULL = default do código. Fase 1b.';
COMMENT ON COLUMN agent_configs.model             IS 'Override per-org do model string. NULL = settings.claude_model_agent. Fase 1b.';
COMMENT ON COLUMN agent_configs.model_temperature IS 'Override per-org da temperature da geração. NULL = default do código (0.3). Fase 1b.';
COMMENT ON COLUMN agent_configs.model_max_tokens  IS 'Override per-org do max_tokens da geração. NULL = default do código (500). Fase 1b. NÃO confundir com max_messages.';

-- ── 3. CHECK constraints (depois dos ADD COLUMN) ──────────────────────────
-- Faixas válidas pros overrides. NULL passa em CHECK por definição (SQL three-
-- valued logic), então o invariante "NULL = nada muda" continua intacto.
-- Guardadas em DO blocks porque ADD CONSTRAINT não suporta IF NOT EXISTS —
-- assim o arquivo segue idempotente e bate com o que rodou no banco.
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'chk_model_temperature'
  ) THEN
    ALTER TABLE agent_configs
      ADD CONSTRAINT chk_model_temperature
      CHECK (model_temperature >= 0 AND model_temperature <= 1);
    RAISE NOTICE 'constraint chk_model_temperature criada (0–1)';
  ELSE
    RAISE NOTICE 'constraint chk_model_temperature: JÁ EXISTE (no-op)';
  END IF;

  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'chk_model_max_tokens'
  ) THEN
    ALTER TABLE agent_configs
      ADD CONSTRAINT chk_model_max_tokens
      CHECK (model_max_tokens > 0);
    RAISE NOTICE 'constraint chk_model_max_tokens criada (> 0)';
  ELSE
    RAISE NOTICE 'constraint chk_model_max_tokens: JÁ EXISTE (no-op)';
  END IF;
END $$;

-- ── 4. Verificação PÓS: colunas + constraints presentes? ──────────────────
-- (Se qualquer condição falhar, RAISE EXCEPTION aborta e o COMMIT não acontece.)
DO $$
DECLARE
  ok_count INT;
  con_count INT;
BEGIN
  SELECT COUNT(*) INTO ok_count
  FROM information_schema.columns
  WHERE table_schema = 'public'
    AND table_name = 'agent_configs'
    AND column_name IN ('llm_provider', 'model', 'model_temperature', 'model_max_tokens')
    AND is_nullable = 'YES'
    AND column_default IS NULL;

  IF ok_count != 4 THEN
    RAISE EXCEPTION 'Verificação falhou: esperava 4 colunas nullable sem default, encontrei %. Migration abortada (rollback).', ok_count;
  END IF;

  SELECT COUNT(*) INTO con_count
  FROM pg_constraint
  WHERE conname IN ('chk_model_temperature', 'chk_model_max_tokens');

  IF con_count != 2 THEN
    RAISE EXCEPTION 'Verificação falhou: esperava 2 CHECK constraints, encontrei %. Migration abortada (rollback).', con_count;
  END IF;

  RAISE NOTICE 'OK: 4 colunas (nullable, sem default) + 2 CHECK constraints. Invariante NULL=nada-muda preservado.';
END $$;

COMMIT;

-- ── Query de validação final (rodar APÓS o commit, opcional) ──────────────
-- SELECT column_name, data_type, is_nullable, column_default
-- FROM information_schema.columns
-- WHERE table_schema = 'public'
--   AND table_name = 'agent_configs'
--   AND column_name IN ('llm_provider', 'model', 'model_temperature', 'model_max_tokens')
-- ORDER BY column_name;
--
-- Esperado: 4 linhas, is_nullable = YES, column_default = NULL para todas.
--
-- Sanidade (nenhuma org deve ter valor setado logo após a migration):
-- SELECT organization_id, agent_type, llm_provider, model, model_temperature, model_max_tokens
-- FROM agent_configs
-- WHERE llm_provider IS NOT NULL OR model IS NOT NULL
--    OR model_temperature IS NOT NULL OR model_max_tokens IS NOT NULL;
-- Esperado: 0 linhas.
