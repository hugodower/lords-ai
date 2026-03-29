-- Campaign Context Migration
-- Adds campaign_context JSONB column to contacts table
-- Stores context from WhatsApp templates and Click-to-WhatsApp Ads
--
-- Usage: Run via Supabase SQL Editor or Management API
-- DO NOT run automatically — manual execution only

ALTER TABLE contacts ADD COLUMN IF NOT EXISTS campaign_context JSONB DEFAULT NULL;

-- Index for querying contacts with active campaign context
CREATE INDEX IF NOT EXISTS idx_contacts_campaign_context
ON contacts USING gin (campaign_context)
WHERE campaign_context IS NOT NULL;

COMMENT ON COLUMN contacts.campaign_context IS 'Campaign/ad context (template_response, ctwa_ad, campaign_label). Expires after 72h.';
