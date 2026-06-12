-- tolerant
DELETE FROM campaign_sequence_steps
WHERE campaign_filename IN ('sequences.json', 'sequences.json.json');

DELETE FROM campaign_sequence_rules
WHERE campaign_filename IN ('sequences.json', 'sequences.json.json');