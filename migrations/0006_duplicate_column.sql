-- tolerant
ALTER TABLE leads ADD COLUMN duplicate_of_lead_id TEXT DEFAULT '';
