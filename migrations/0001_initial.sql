CREATE TABLE IF NOT EXISTS pipeline_runs (
    id TEXT PRIMARY KEY,
    status TEXT,
    filters TEXT,
    enrichment_mode TEXT,
    total_scraped INT DEFAULT 0,
    total_enriched INT DEFAULT 0,
    total_warm INT DEFAULT 0,
    total_cold INT DEFAULT 0,
    total_no_email INT DEFAULT 0,
    total_exported INT DEFAULT 0,
    error TEXT DEFAULT '',
    started_at TEXT,
    completed_at TEXT
);

CREATE TABLE IF NOT EXISTS leads (
    id TEXT PRIMARY KEY,
    run_id TEXT,
    full_name TEXT,
    first_name TEXT,
    last_name TEXT,
    title TEXT,
    company TEXT,
    company_domain TEXT,
    location TEXT,
    linkedin_url TEXT,
    company_linkedin_url TEXT,
    email TEXT,
    email_confidence TEXT,
    phone TEXT,
    duplicate_of_lead_id TEXT DEFAULT '',
    intent_score REAL DEFAULT 0,
    segment TEXT,
    status TEXT,
    created_at TEXT,
    updated_at TEXT,
    FOREIGN KEY(run_id) REFERENCES pipeline_runs(id)
);

CREATE TABLE IF NOT EXISTS agent_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT,
    event_type TEXT,
    agent_name TEXT,
    payload TEXT,
    error TEXT,
    timestamp TEXT
);

CREATE TABLE IF NOT EXISTS run_checkpoints (
    run_id TEXT PRIMARY KEY,
    last_page INT DEFAULT 0,
    leads_collected INT DEFAULT 0,
    updated_at TEXT
);

CREATE TABLE IF NOT EXISTS lead_universes (
    id TEXT PRIMARY KEY,
    name TEXT,
    campaign_filename TEXT,
    source_type TEXT DEFAULT 'sales_navigator',
    description TEXT DEFAULT '',
    target_leads INT DEFAULT 0,
    total_scraped INT DEFAULT 0,
    total_unique INT DEFAULT 0,
    status TEXT DEFAULT 'queued',
    created_at TEXT,
    updated_at TEXT
);

CREATE TABLE IF NOT EXISTS lead_source_segments (
    id TEXT PRIMARY KEY,
    universe_id TEXT,
    campaign_filename TEXT,
    source_url TEXT,
    label TEXT,
    filters_json TEXT DEFAULT '{}',
    expected_count INT DEFAULT 0,
    scraped_count INT DEFAULT 0,
    unique_count INT DEFAULT 0,
    duplicate_count INT DEFAULT 0,
    status TEXT DEFAULT 'queued',
    stop_reason TEXT DEFAULT '',
    last_run_id TEXT DEFAULT '',
    created_at TEXT,
    updated_at TEXT,
    FOREIGN KEY(universe_id) REFERENCES lead_universes(id)
);

CREATE TABLE IF NOT EXISTS campaign_sequence_steps (
    id TEXT PRIMARY KEY,
    campaign_filename TEXT NOT NULL,
    touch_number INT NOT NULL,
    touch_name TEXT DEFAULT '',
    delay_days INT DEFAULT 0,
    delay_value INT DEFAULT 0,
    delay_unit TEXT DEFAULT 'days',
    delay_type TEXT DEFAULT 'calendar_days',
    send_time_mode TEXT DEFAULT 'same_as_previous',
    fixed_send_time TEXT DEFAULT '',
    subject_template TEXT DEFAULT '',
    email_body_template TEXT DEFAULT '',
    linkedin_message_template TEXT DEFAULT '',
    is_active INT DEFAULT 1,
    created_at TEXT,
    updated_at TEXT
);

CREATE TABLE IF NOT EXISTS campaign_sequence_rules (
    id TEXT PRIMARY KEY,
    campaign_filename TEXT NOT NULL UNIQUE,
    timezone TEXT DEFAULT 'Asia/Karachi',
    mode TEXT DEFAULT 'manual',
    stop_on_reply INT DEFAULT 1,
    stop_on_bounce INT DEFAULT 1,
    stop_on_unsubscribe INT DEFAULT 1,
    skip_no_email INT DEFAULT 1,
    skip_weekends INT DEFAULT 1,
    send_window_start TEXT DEFAULT '09:00',
    send_window_end TEXT DEFAULT '17:00',
    daily_send_limit INT DEFAULT 50,
    delay_between_sends_seconds INT DEFAULT 60,
    require_approval_for_touch1 INT DEFAULT 1,
    require_approval_for_followups INT DEFAULT 1,
    created_at TEXT,
    updated_at TEXT
);

CREATE TABLE IF NOT EXISTS outreach_drafts (
    id TEXT PRIMARY KEY,
    lead_id TEXT NOT NULL,
    campaign_filename TEXT NOT NULL,
    touch_number INT NOT NULL,
    subject TEXT DEFAULT '',
    body TEXT DEFAULT '',
    linkedin_message TEXT DEFAULT '',
    status TEXT DEFAULT 'draft',
    scheduled_for TEXT,
    sent_at TEXT,
    error_message TEXT DEFAULT '',
    created_at TEXT,
    updated_at TEXT,
    FOREIGN KEY(lead_id) REFERENCES leads(id)
);

CREATE TABLE IF NOT EXISTS lead_sequence_state (
    id TEXT PRIMARY KEY,
    lead_id TEXT NOT NULL,
    campaign_filename TEXT NOT NULL,
    current_touch INT DEFAULT 0,
    status TEXT DEFAULT 'not_started',
    last_touch_sent_at TEXT,
    next_touch_due_at TEXT,
    completed_at TEXT,
    stop_reason TEXT DEFAULT '',
    created_at TEXT,
    updated_at TEXT,
    FOREIGN KEY(lead_id) REFERENCES leads(id)
);

CREATE TABLE IF NOT EXISTS lead_activities (
    id TEXT PRIMARY KEY,
    lead_id TEXT NOT NULL,
    campaign_filename TEXT NOT NULL,
    run_id TEXT DEFAULT '',
    activity_type TEXT NOT NULL,
    title TEXT DEFAULT '',
    description TEXT DEFAULT '',
    metadata_json TEXT DEFAULT '',
    created_at TEXT,
    FOREIGN KEY(lead_id) REFERENCES leads(id)
);

CREATE TABLE IF NOT EXISTS suppression (
    email TEXT PRIMARY KEY,
    reason TEXT NOT NULL,
    source_lead_id TEXT DEFAULT '',
    source_campaign TEXT DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS kv_store (
    key TEXT PRIMARY KEY,
    value TEXT,
    updated_at TEXT
);

CREATE TABLE IF NOT EXISTS send_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    lead_id TEXT,
    campaign_filename TEXT,
    to_email TEXT,
    to_domain TEXT,
    touch_number INT,
    sent_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_send_log_day
    ON send_log(sent_at);

CREATE INDEX IF NOT EXISTS idx_send_log_domain
    ON send_log(to_domain, sent_at);

CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    type TEXT NOT NULL,
    status TEXT NOT NULL,
    total INT DEFAULT 0,
    done INT DEFAULT 0,
    failed INT DEFAULT 0,
    skipped INT DEFAULT 0,
    payload_json TEXT DEFAULT '{}',
    result_json TEXT DEFAULT '{}',
    error TEXT DEFAULT '',
    cancel_requested INT DEFAULT 0,
    created_at TEXT NOT NULL,
    started_at TEXT DEFAULT '',
    finished_at TEXT DEFAULT '',
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_jobs_status_created
    ON jobs(status, created_at);

CREATE INDEX IF NOT EXISTS idx_jobs_type_created
    ON jobs(type, created_at);

CREATE INDEX IF NOT EXISTS idx_leads_run
    ON leads(run_id);

CREATE INDEX IF NOT EXISTS idx_events_run
    ON agent_events(run_id);

CREATE INDEX IF NOT EXISTS idx_segments_universe
    ON lead_source_segments(universe_id);

CREATE INDEX IF NOT EXISTS idx_universes_campaign
    ON lead_universes(campaign_filename);

CREATE UNIQUE INDEX IF NOT EXISTS idx_sequence_steps_campaign_touch
    ON campaign_sequence_steps(campaign_filename, touch_number);

CREATE INDEX IF NOT EXISTS idx_outreach_drafts_campaign
    ON outreach_drafts(campaign_filename, status, touch_number);

CREATE INDEX IF NOT EXISTS idx_outreach_drafts_lead
    ON outreach_drafts(lead_id, campaign_filename, touch_number);

CREATE UNIQUE INDEX IF NOT EXISTS idx_active_outreach_draft
    ON outreach_drafts(lead_id, campaign_filename, touch_number)
    WHERE status NOT IN ('failed', 'skipped');

CREATE UNIQUE INDEX IF NOT EXISTS idx_lead_sequence_state
    ON lead_sequence_state(lead_id, campaign_filename);

CREATE INDEX IF NOT EXISTS idx_lead_sequence_due
    ON lead_sequence_state(campaign_filename, status, next_touch_due_at);

CREATE INDEX IF NOT EXISTS idx_lead_activities_campaign
    ON lead_activities(campaign_filename, created_at);

CREATE INDEX IF NOT EXISTS idx_lead_activities_lead
    ON lead_activities(lead_id, campaign_filename, created_at);
