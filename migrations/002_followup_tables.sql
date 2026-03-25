-- =====================================================
-- LORDS AI — Fase 2: Follow-up Automático
-- =====================================================

-- Fila de follow-ups agendados
CREATE TABLE IF NOT EXISTS followup_queue (
  id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
  conversation_id INTEGER NOT NULL,
  contact_phone TEXT NOT NULL,
  contact_name TEXT,
  template_name TEXT NOT NULL,
  template_variables JSONB DEFAULT '[]',
  scheduled_at TIMESTAMPTZ NOT NULL,
  sent_at TIMESTAMPTZ,
  status TEXT DEFAULT 'pending' CHECK (status IN ('pending', 'sent', 'cancelled', 'failed')),
  created_at TIMESTAMPTZ DEFAULT now(),
  metadata JSONB DEFAULT '{}'
);

-- Índices para performance
CREATE INDEX IF NOT EXISTS idx_followup_pending
  ON followup_queue(status, scheduled_at)
  WHERE status = 'pending';

CREATE INDEX IF NOT EXISTS idx_followup_conv
  ON followup_queue(conversation_id, template_name);

CREATE INDEX IF NOT EXISTS idx_followup_org
  ON followup_queue(organization_id);

-- Configuração de follow-up por organização
CREATE TABLE IF NOT EXISTS followup_config (
  id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
  followup_enabled BOOLEAN DEFAULT true,
  followup_24h_enabled BOOLEAN DEFAULT true,
  followup_48h_enabled BOOLEAN DEFAULT true,
  reativacao_7d_enabled BOOLEAN DEFAULT true,
  confirmacao_enabled BOOLEAN DEFAULT true,
  lembrete_enabled BOOLEAN DEFAULT true,
  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now(),
  UNIQUE(organization_id)
);

-- RLS
ALTER TABLE followup_queue ENABLE ROW LEVEL SECURITY;
ALTER TABLE followup_config ENABLE ROW LEVEL SECURITY;

-- service_role (Python backend) has full access
CREATE POLICY "service_role_all" ON followup_queue FOR ALL USING (true) WITH CHECK (true);
CREATE POLICY "service_role_all" ON followup_config FOR ALL USING (true) WITH CHECK (true);
