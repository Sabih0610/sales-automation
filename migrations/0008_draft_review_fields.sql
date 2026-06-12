-- tolerant
ALTER TABLE outreach_drafts ADD COLUMN research_summary TEXT DEFAULT '';
ALTER TABLE outreach_drafts ADD COLUMN kb_sources TEXT DEFAULT '[]';
ALTER TABLE outreach_drafts ADD COLUMN risk_flags TEXT DEFAULT '[]';