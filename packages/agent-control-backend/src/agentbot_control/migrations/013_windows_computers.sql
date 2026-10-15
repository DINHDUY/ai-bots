CREATE TABLE paired_computers (
 id TEXT PRIMARY KEY, owner_id TEXT NOT NULL REFERENCES users(id), name TEXT NOT NULL,
 token_hash TEXT NOT NULL UNIQUE, created_at TEXT NOT NULL, revoked_at TEXT
);
CREATE TABLE computer_enrollments (
 id TEXT PRIMARY KEY, owner_id TEXT NOT NULL REFERENCES users(id), secret_hash TEXT NOT NULL UNIQUE,
 expires_at TEXT NOT NULL, consumed_at TEXT, request_id TEXT NOT NULL,
 UNIQUE(owner_id,request_id)
);
CREATE TABLE bot_compute_config (
 bot_id TEXT PRIMARY KEY REFERENCES bots(id) ON DELETE CASCADE,
 device_id TEXT NOT NULL REFERENCES paired_computers(id), revision INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE windows_bindings (
 session_id TEXT PRIMARY KEY, bot_id TEXT NOT NULL, device_id TEXT NOT NULL REFERENCES paired_computers(id),
 generation INTEGER NOT NULL, active INTEGER NOT NULL DEFAULT 1
);
CREATE UNIQUE INDEX one_windows_binding ON windows_bindings(device_id) WHERE active=1;
