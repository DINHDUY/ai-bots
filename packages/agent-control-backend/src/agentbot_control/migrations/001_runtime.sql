CREATE TABLE workspaces (
    id TEXT PRIMARY KEY, owner_id TEXT NOT NULL UNIQUE REFERENCES users(id), name TEXT NOT NULL
);
CREATE TABLE workspace_members (
    workspace_id TEXT REFERENCES workspaces(id), user_id TEXT REFERENCES users(id), role TEXT NOT NULL,
    PRIMARY KEY (workspace_id, user_id)
);
CREATE TABLE bot_streams (
    bot_id TEXT PRIMARY KEY REFERENCES bots(id) ON DELETE CASCADE,
    workspace_id TEXT NOT NULL REFERENCES workspaces(id), seq INTEGER NOT NULL DEFAULT 0,
    floor_seq INTEGER NOT NULL DEFAULT 0, imported INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE computer_sessions (
    id TEXT PRIMARY KEY, bot_id TEXT NOT NULL REFERENCES bots(id) ON DELETE CASCADE,
    generation INTEGER NOT NULL, status TEXT NOT NULL, created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL, UNIQUE(bot_id, generation)
);
CREATE UNIQUE INDEX one_computer ON computer_sessions(bot_id) WHERE status != 'closed';
CREATE TABLE runs (
    id TEXT PRIMARY KEY, bot_id TEXT NOT NULL REFERENCES bots(id) ON DELETE CASCADE,
    session_id TEXT NOT NULL REFERENCES computer_sessions(id), user_id TEXT NOT NULL REFERENCES users(id),
    status TEXT NOT NULL, prompt TEXT NOT NULL, config TEXT NOT NULL, trigger TEXT NOT NULL,
    created_at TEXT NOT NULL, updated_at TEXT NOT NULL, outcome TEXT
);
CREATE UNIQUE INDEX one_active_run ON runs(bot_id)
    WHERE status IN ('preparing', 'running', 'awaiting_approval', 'stopping');
CREATE TABLE actions (
    id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    name TEXT NOT NULL, argument_digest TEXT NOT NULL, status TEXT NOT NULL
);
CREATE TABLE approvals (
    id TEXT PRIMARY KEY, bot_id TEXT NOT NULL REFERENCES bots(id) ON DELETE CASCADE,
    run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    action_id TEXT NOT NULL REFERENCES actions(id), action TEXT NOT NULL, detail TEXT NOT NULL,
    status TEXT NOT NULL, expires_at TEXT NOT NULL, created_at TEXT NOT NULL,
    revision INTEGER NOT NULL DEFAULT 1, decided_by TEXT
);
CREATE TABLE bot_events (
    event_id TEXT PRIMARY KEY, bot_id TEXT NOT NULL REFERENCES bots(id) ON DELETE CASCADE,
    seq INTEGER NOT NULL, occurred_at TEXT NOT NULL, envelope TEXT NOT NULL, UNIQUE(bot_id, seq)
);
CREATE TABLE messages (
    id TEXT NOT NULL UNIQUE, bot_id TEXT NOT NULL REFERENCES bots(id) ON DELETE CASCADE,
    seq INTEGER NOT NULL, role TEXT NOT NULL, content TEXT NOT NULL, occurred_at TEXT,
    ordinal INTEGER PRIMARY KEY AUTOINCREMENT
);
CREATE TABLE command_receipts (
    bot_id TEXT NOT NULL REFERENCES bots(id) ON DELETE CASCADE, request_id TEXT NOT NULL,
    fingerprint TEXT NOT NULL, response TEXT NOT NULL, PRIMARY KEY(bot_id, request_id)
);
CREATE TABLE capture_records (
    id TEXT PRIMARY KEY, bot_id TEXT NOT NULL REFERENCES bots(id) ON DELETE CASCADE,
    size INTEGER NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE runtime_settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);

