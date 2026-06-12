CREATE TABLE IF NOT EXISTS campaigns (
    id TEXT PRIMARY KEY,
    filename TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    description TEXT DEFAULT '',
    config TEXT NOT NULL DEFAULT '{}',
    created_at TEXT,
    updated_at TEXT
);
