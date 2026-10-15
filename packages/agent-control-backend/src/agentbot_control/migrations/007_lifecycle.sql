CREATE TABLE lifecycle_operations (
 id TEXT PRIMARY KEY, bot_id TEXT NOT NULL REFERENCES bots(id) ON DELETE CASCADE,
 request_id TEXT NOT NULL, fingerprint TEXT NOT NULL, session_id TEXT,
 operation TEXT NOT NULL, status TEXT NOT NULL, result TEXT, created_at TEXT NOT NULL,
 UNIQUE(bot_id,request_id)
);
CREATE TABLE computer_retention (
 session_id TEXT PRIMARY KEY REFERENCES computer_sessions(id), keep_warm_until TEXT,
 retain_until TEXT, warned INTEGER NOT NULL DEFAULT 0
);
