ALTER TABLE actions ADD COLUMN session_id TEXT;
ALTER TABLE actions ADD COLUMN generation INTEGER;
ALTER TABLE actions ADD COLUMN arguments_sealed TEXT;
ALTER TABLE actions ADD COLUMN context TEXT NOT NULL DEFAULT '{}';
ALTER TABLE actions ADD COLUMN step_id TEXT;
ALTER TABLE actions ADD COLUMN result TEXT;
ALTER TABLE actions ADD COLUMN started_at TEXT;
ALTER TABLE actions ADD COLUMN ended_at TEXT;
ALTER TABLE approvals ADD COLUMN generation INTEGER;
ALTER TABLE approvals ADD COLUMN argument_digest TEXT;
ALTER TABLE approvals ADD COLUMN policy_id TEXT;
ALTER TABLE approvals ADD COLUMN policy_version INTEGER;
ALTER TABLE approvals ADD COLUMN policy_scope TEXT;
CREATE TABLE approval_policies (
    id TEXT PRIMARY KEY,
    bot_id TEXT NOT NULL REFERENCES bots(id) ON DELETE CASCADE,
    operation TEXT NOT NULL,
    constraints_sealed TEXT NOT NULL,
    summary TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    created_at TEXT NOT NULL,
    created_by TEXT NOT NULL REFERENCES users(id),
    version INTEGER NOT NULL DEFAULT 1,
    revoked_at TEXT,
    revoked_by TEXT
);
CREATE INDEX policies_by_bot ON approval_policies(bot_id, expires_at);
CREATE INDEX approvals_by_run ON approvals(run_id, status);
CREATE TABLE run_plans (
    run_id TEXT PRIMARY KEY REFERENCES runs(id) ON DELETE CASCADE,
    steps TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
