CREATE TABLE terminals (
 id TEXT PRIMARY KEY, bot_id TEXT NOT NULL REFERENCES bots(id) ON DELETE CASCADE,
 session_id TEXT NOT NULL REFERENCES computer_sessions(id), lease_id TEXT NOT NULL REFERENCES control_leases(id),
 native_id TEXT NOT NULL, status TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE UNIQUE INDEX terminal_per_lease ON terminals(lease_id) WHERE status='open';
