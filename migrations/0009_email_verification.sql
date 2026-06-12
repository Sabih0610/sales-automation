-- tolerant
ALTER TABLE leads ADD COLUMN email_verification_status TEXT DEFAULT '';
ALTER TABLE leads ADD COLUMN email_verification_reason TEXT DEFAULT '';
ALTER TABLE leads ADD COLUMN email_verification_checked_at TEXT DEFAULT '';

CREATE INDEX IF NOT EXISTS idx_leads_email_verification_status
ON leads(email_verification_status);