CREATE TABLE computer_health (session_id TEXT PRIMARY KEY REFERENCES computer_sessions(id) ON DELETE CASCADE, observed_at TEXT NOT NULL, report TEXT NOT NULL);
ALTER TABLE capture_records ADD COLUMN session_id TEXT;
ALTER TABLE capture_records ADD COLUMN metadata TEXT;
CREATE INDEX captures_by_session ON capture_records(bot_id,session_id,created_at);
