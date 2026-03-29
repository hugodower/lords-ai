-- =============================================================
-- LORDS CRM — AI Agent Virtual Users
-- Creates virtual user for Aurora AI agent
-- =============================================================
-- Run manually in Supabase SQL Editor
-- =============================================================

-- ══════════════════════════════════════════════════════════════
-- 1. Expand org_members role CHECK to allow 'ai_agent'
-- ══════════════════════════════════════════════════════════════
ALTER TABLE public.org_members DROP CONSTRAINT IF EXISTS org_members_role_check;
ALTER TABLE public.org_members ADD CONSTRAINT org_members_role_check
  CHECK (role = ANY (ARRAY['org_admin', 'org_member', 'org_agent', 'ai_agent']));

-- ══════════════════════════════════════════════════════════════
-- 2. Create virtual user in auth.users for Aurora
--    No password → cannot login. Marked via raw_user_meta_data.
-- ══════════════════════════════════════════════════════════════
INSERT INTO auth.users (
  id, instance_id, aud, role, email,
  encrypted_password, email_confirmed_at,
  raw_app_meta_data, raw_user_meta_data,
  is_sso_user, is_anonymous,
  created_at, updated_at
) VALUES (
  'a0000000-0000-0000-0000-000000000001',
  '00000000-0000-0000-0000-000000000000',
  'authenticated',
  'authenticated',
  'aurora@ai.lordsads.uk',
  '',  -- empty password = cannot login
  NOW(),
  '{"provider": "virtual", "providers": ["virtual"]}'::jsonb,
  '{"full_name": "Aurora", "is_ai_agent": true}'::jsonb,
  false,
  false,
  NOW(),
  NOW()
) ON CONFLICT (id) DO NOTHING;

-- ══════════════════════════════════════════════════════════════
-- 3. Add Aurora as ai_agent member of LORDS org
-- ══════════════════════════════════════════════════════════════
INSERT INTO public.org_members (organization_id, user_id, role)
VALUES (
  'cc000000-0000-0000-0000-000000000001',  -- LORDS ADS | AI Solutions
  'a0000000-0000-0000-0000-000000000001',  -- Aurora
  'ai_agent'
) ON CONFLICT DO NOTHING;

-- ══════════════════════════════════════════════════════════════
-- 4. Add Aurora as ai_agent member of Demo org
-- ══════════════════════════════════════════════════════════════
INSERT INTO public.org_members (organization_id, user_id, role)
VALUES (
  'aa000000-0000-0000-0000-000000000001',  -- Organizacao Demonstracao LORDS
  'a0000000-0000-0000-0000-000000000001',  -- Aurora
  'ai_agent'
) ON CONFLICT DO NOTHING;

-- ══════════════════════════════════════════════════════════════
-- 5. Verify
-- ══════════════════════════════════════════════════════════════
SELECT u.id, u.email, u.raw_user_meta_data->>'full_name' AS name,
       m.organization_id, m.role
FROM auth.users u
LEFT JOIN public.org_members m ON m.user_id = u.id
WHERE u.id = 'a0000000-0000-0000-0000-000000000001';

-- Reload schema cache
NOTIFY pgrst, 'reload schema';
