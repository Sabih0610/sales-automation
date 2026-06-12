-- tolerant
ALTER TABLE leads ADD COLUMN lead_universe_id TEXT DEFAULT '';
ALTER TABLE leads ADD COLUMN lead_source_segment_id TEXT DEFAULT '';
ALTER TABLE leads ADD COLUMN email_subject TEXT DEFAULT '';
ALTER TABLE leads ADD COLUMN email_body TEXT DEFAULT '';
ALTER TABLE leads ADD COLUMN linkedin_message TEXT DEFAULT '';
ALTER TABLE leads ADD COLUMN research_summary TEXT DEFAULT '';
ALTER TABLE leads ADD COLUMN campaign_name TEXT DEFAULT '';
ALTER TABLE leads ADD COLUMN personalised_at TEXT;
ALTER TABLE leads ADD COLUMN email_sequence_status TEXT DEFAULT 'not_started';
ALTER TABLE leads ADD COLUMN day1_sent_at TEXT;
ALTER TABLE leads ADD COLUMN day3_sent_at TEXT;
ALTER TABLE leads ADD COLUMN day7_sent_at TEXT;
ALTER TABLE leads ADD COLUMN email_sequence_error TEXT DEFAULT '';

ALTER TABLE campaign_sequence_steps ADD COLUMN delay_value INT DEFAULT 0;
ALTER TABLE campaign_sequence_steps ADD COLUMN delay_unit TEXT DEFAULT 'days';
ALTER TABLE campaign_sequence_steps ADD COLUMN delay_type TEXT DEFAULT 'calendar_days';
ALTER TABLE campaign_sequence_steps ADD COLUMN send_time_mode TEXT DEFAULT 'same_as_previous';
ALTER TABLE campaign_sequence_steps ADD COLUMN fixed_send_time TEXT DEFAULT '';

UPDATE campaign_sequence_steps
SET delay_value = COALESCE(NULLIF(delay_value, 0), delay_days),
    delay_unit = COALESCE(NULLIF(delay_unit, ''), 'days'),
    delay_type = COALESCE(NULLIF(delay_type, ''), 'calendar_days'),
    send_time_mode = COALESCE(NULLIF(send_time_mode, ''), 'same_as_previous');

ALTER TABLE campaign_sequence_rules ADD COLUMN timezone TEXT DEFAULT 'Asia/Karachi';
ALTER TABLE campaign_sequence_rules ADD COLUMN mode TEXT DEFAULT 'manual';
ALTER TABLE campaign_sequence_rules ADD COLUMN require_approval_for_touch1 INT DEFAULT 1;
ALTER TABLE campaign_sequence_rules ADD COLUMN require_approval_for_followups INT DEFAULT 1;
