-- tolerant
ALTER TABLE campaign_sequence_rules ADD COLUMN mode TEXT DEFAULT 'manual';
UPDATE campaign_sequence_rules
SET mode = 'manual'
WHERE mode IS NULL OR mode = '' OR mode = 'review';
UPDATE campaign_sequence_rules
SET mode = 'auto'
WHERE mode = 'autopilot';
