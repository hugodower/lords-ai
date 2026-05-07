-- Migration: adicionar chatwoot_agent_email + popular Ana e Aurora
-- Data: 2026-05-06
-- Autor: Hugo
--
-- BACKGROUND:
-- A coluna chatwoot_agent_email não existia na tabela agent_configs.
-- O código atual usa fallback silencioso para DEFAULT_AI_AGENT_EMAIL.
-- Ana precisa de configuração própria para auto-atribuição funcionar.

BEGIN;

-- 1. Criar coluna (instantânea, não bloqueia tabela)
ALTER TABLE agent_configs
  ADD COLUMN IF NOT EXISTS chatwoot_agent_email TEXT;

-- 2. Popular Ana (Lebedenco)
UPDATE agent_configs
SET chatwoot_agent_email = 'ana@ai.lebedenco.uk',
    handoff_agent_id = 3
WHERE organization_id = '31ddcc20-868c-4988-9326-e15d7a27d06f'
  AND agent_type = 'sdr';

-- 3. Popular Aurora (LORDS Ads) — preservar comportamento atual
UPDATE agent_configs
SET chatwoot_agent_email = 'aurora@ai.lordsads.uk'
WHERE organization_id = 'cc000000-0000-0000-0000-000000000001'
  AND agent_type = 'sdr';

-- 4. Validação (não comita se algo estiver errado)
DO $$
DECLARE
  ana_count INTEGER;
  aurora_count INTEGER;
BEGIN
  SELECT COUNT(*) INTO ana_count
  FROM agent_configs
  WHERE organization_id = '31ddcc20-868c-4988-9326-e15d7a27d06f'
    AND agent_type = 'sdr'
    AND chatwoot_agent_email = 'ana@ai.lebedenco.uk'
    AND handoff_agent_id = 3;

  SELECT COUNT(*) INTO aurora_count
  FROM agent_configs
  WHERE organization_id = 'cc000000-0000-0000-0000-000000000001'
    AND agent_type = 'sdr'
    AND chatwoot_agent_email = 'aurora@ai.lordsads.uk';

  IF ana_count != 1 THEN
    RAISE EXCEPTION 'Ana update falhou — esperado 1 row, got %', ana_count;
  END IF;

  IF aurora_count != 1 THEN
    RAISE EXCEPTION 'Aurora update falhou — esperado 1 row, got %', aurora_count;
  END IF;

  RAISE NOTICE 'Migration executada com sucesso: Ana e Aurora configuradas';
END $$;

COMMIT;

-- Query de validação final (executar após migration):
-- SELECT organization_id, agent_type, agent_name, chatwoot_agent_email,
--        handoff_agent_id, is_active
-- FROM agent_configs
-- WHERE organization_id IN (
--   '31ddcc20-868c-4988-9326-e15d7a27d06f',
--   'cc000000-0000-0000-0000-000000000001'
-- );