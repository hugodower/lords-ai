-- =====================================================
-- LORDS AI — Fase 1: Agent Tables Migration
-- =====================================================

-- Configuração geral dos agentes por organização
CREATE TABLE IF NOT EXISTS agent_configs (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
  agent_type VARCHAR(20) NOT NULL CHECK (agent_type IN ('sdr', 'support', 'closer', 'retention')),
  is_active BOOLEAN DEFAULT false,
  agent_name VARCHAR(100) DEFAULT 'Ana',
  personality TEXT,
  claude_api_key TEXT,
  max_messages INT DEFAULT 10,
  max_response_time_seconds INT DEFAULT 10,
  handoff_agent_id INT,
  handoff_agent_name VARCHAR(100),
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW(),
  UNIQUE(organization_id, agent_type)
);

-- Horário de funcionamento
CREATE TABLE IF NOT EXISTS business_hours (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
  day_of_week INT NOT NULL CHECK (day_of_week BETWEEN 0 AND 6),
  is_open BOOLEAN DEFAULT true,
  open_time TIME,
  close_time TIME,
  UNIQUE(organization_id, day_of_week)
);

-- Mensagem fora do horário
CREATE TABLE IF NOT EXISTS business_hours_config (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
  after_hours_message TEXT DEFAULT 'Olá! No momento estamos fechados. Retornamos no próximo dia útil!',
  after_hours_behavior VARCHAR(20) DEFAULT 'reply_and_stop' CHECK (after_hours_behavior IN ('reply_and_stop', 'reply_and_qualify', 'silent')),
  UNIQUE(organization_id)
);

-- Etapas de qualificação (roteiro do SDR)
CREATE TABLE IF NOT EXISTS qualification_steps (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
  agent_type VARCHAR(20) DEFAULT 'sdr',
  step_order INT NOT NULL,
  question TEXT NOT NULL,
  is_required BOOLEAN DEFAULT true,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  UNIQUE(organization_id, agent_type, step_order)
);

-- Critérios de lead quente
CREATE TABLE IF NOT EXISTS lead_hot_criteria (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
  criteria_description TEXT NOT NULL,
  UNIQUE(organization_id)
);

-- Respostas rápidas (FAQ)
CREATE TABLE IF NOT EXISTS quick_responses (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
  trigger_keyword VARCHAR(100) NOT NULL,
  response_text TEXT NOT NULL,
  is_active BOOLEAN DEFAULT true,
  UNIQUE(organization_id, trigger_keyword)
);

-- Tópicos proibidos
CREATE TABLE IF NOT EXISTS forbidden_topics (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
  topic TEXT NOT NULL,
  UNIQUE(organization_id, topic)
);

-- Dados da empresa (para contexto da IA)
CREATE TABLE IF NOT EXISTS company_info (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
  company_name VARCHAR(255),
  segment VARCHAR(100),
  description TEXT,
  address TEXT,
  website VARCHAR(255),
  payment_methods TEXT,
  differentials TEXT,
  UNIQUE(organization_id)
);

-- Configuração de agendamento
CREATE TABLE IF NOT EXISTS scheduling_config (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
  scheduling_type VARCHAR(20) DEFAULT 'collect_preference' CHECK (scheduling_type IN ('external_link', 'google_calendar', 'collect_preference')),
  external_link VARCHAR(500),
  google_calendar_id VARCHAR(255),
  google_oauth_token JSONB,
  slot_duration_minutes INT DEFAULT 60,
  buffer_minutes INT DEFAULT 15,
  available_start_time TIME DEFAULT '08:00',
  available_end_time TIME DEFAULT '17:00',
  min_advance_hours INT DEFAULT 2,
  max_advance_days INT DEFAULT 30,
  booking_message TEXT DEFAULT 'Pronto! Agendei para {data} às {hora}. Qualquer dúvida é só chamar!',
  UNIQUE(organization_id)
);

-- Log de conversas da IA
CREATE TABLE IF NOT EXISTS ai_conversation_logs (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
  conversation_id VARCHAR(50) NOT NULL,
  contact_phone VARCHAR(20),
  contact_name VARCHAR(255),
  agent_type VARCHAR(20) NOT NULL,
  message_role VARCHAR(20) NOT NULL CHECK (message_role IN ('user', 'assistant', 'system')),
  message_text TEXT NOT NULL,
  skill_used VARCHAR(50),
  action_taken VARCHAR(50),
  validation_result VARCHAR(50),
  tokens_used INT,
  cost_usd DECIMAL(10,6),
  response_time_ms INT,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Índices para performance
CREATE INDEX IF NOT EXISTS idx_ai_logs_org ON ai_conversation_logs(organization_id);
CREATE INDEX IF NOT EXISTS idx_ai_logs_conv ON ai_conversation_logs(conversation_id);
CREATE INDEX IF NOT EXISTS idx_ai_logs_created ON ai_conversation_logs(created_at);

-- Marcar deals com participação da IA
ALTER TABLE deals ADD COLUMN IF NOT EXISTS ai_participated BOOLEAN DEFAULT false;
ALTER TABLE deals ADD COLUMN IF NOT EXISTS ai_agent_type VARCHAR(20);
ALTER TABLE deals ADD COLUMN IF NOT EXISTS ai_qualified_at TIMESTAMPTZ;

-- =====================================================
-- RLS Policies
-- =====================================================

ALTER TABLE agent_configs ENABLE ROW LEVEL SECURITY;
ALTER TABLE business_hours ENABLE ROW LEVEL SECURITY;
ALTER TABLE business_hours_config ENABLE ROW LEVEL SECURITY;
ALTER TABLE qualification_steps ENABLE ROW LEVEL SECURITY;
ALTER TABLE lead_hot_criteria ENABLE ROW LEVEL SECURITY;
ALTER TABLE quick_responses ENABLE ROW LEVEL SECURITY;
ALTER TABLE forbidden_topics ENABLE ROW LEVEL SECURITY;
ALTER TABLE company_info ENABLE ROW LEVEL SECURITY;
ALTER TABLE scheduling_config ENABLE ROW LEVEL SECURITY;
ALTER TABLE ai_conversation_logs ENABLE ROW LEVEL SECURITY;

-- service_role (Python backend) has full access
CREATE POLICY "service_role_all" ON agent_configs FOR ALL USING (true) WITH CHECK (true);
CREATE POLICY "service_role_all" ON business_hours FOR ALL USING (true) WITH CHECK (true);
CREATE POLICY "service_role_all" ON business_hours_config FOR ALL USING (true) WITH CHECK (true);
CREATE POLICY "service_role_all" ON qualification_steps FOR ALL USING (true) WITH CHECK (true);
CREATE POLICY "service_role_all" ON lead_hot_criteria FOR ALL USING (true) WITH CHECK (true);
CREATE POLICY "service_role_all" ON quick_responses FOR ALL USING (true) WITH CHECK (true);
CREATE POLICY "service_role_all" ON forbidden_topics FOR ALL USING (true) WITH CHECK (true);
CREATE POLICY "service_role_all" ON company_info FOR ALL USING (true) WITH CHECK (true);
CREATE POLICY "service_role_all" ON scheduling_config FOR ALL USING (true) WITH CHECK (true);
CREATE POLICY "service_role_all" ON ai_conversation_logs FOR ALL USING (true) WITH CHECK (true);
