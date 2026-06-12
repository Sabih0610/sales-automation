-- tolerant
ALTER TABLE leads DROP COLUMN day1_sent_at;
ALTER TABLE leads DROP COLUMN day3_sent_at;
ALTER TABLE leads DROP COLUMN day7_sent_at;
ALTER TABLE leads DROP COLUMN email_sequence_error;
