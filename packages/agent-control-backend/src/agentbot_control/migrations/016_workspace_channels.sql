CREATE TABLE runs_new (
    id TEXT PRIMARY KEY, bot_id TEXT NOT NULL REFERENCES bots(id) ON DELETE CASCADE,
    session_id TEXT REFERENCES computer_sessions(id), user_id TEXT NOT NULL REFERENCES users(id),
    status TEXT NOT NULL, prompt TEXT NOT NULL, config TEXT NOT NULL, trigger TEXT NOT NULL,
    created_at TEXT NOT NULL, updated_at TEXT NOT NULL, outcome TEXT
);
INSERT INTO runs_new SELECT * FROM runs;
DROP TABLE runs;
ALTER TABLE runs_new RENAME TO runs;
CREATE UNIQUE INDEX one_active_run ON runs(bot_id)
    WHERE status IN ('preparing','running','awaiting_approval','stopping');

CREATE TABLE workspace_channels (
    workspace_id TEXT PRIMARY KEY REFERENCES workspaces(id), enabled INTEGER NOT NULL DEFAULT 0,
    revision INTEGER NOT NULL DEFAULT 0, seq INTEGER NOT NULL DEFAULT 0,
    floor_seq INTEGER NOT NULL DEFAULT 0, directory_revision INTEGER NOT NULL DEFAULT 0
);
INSERT INTO workspace_channels(workspace_id) SELECT id FROM workspaces;
CREATE TABLE channel_enrollment_policies (
    workspace_id TEXT NOT NULL REFERENCES workspace_channels(workspace_id), owner_id TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 0, PRIMARY KEY(workspace_id,owner_id)
);
CREATE TABLE workspace_bot_directory (
    bot_id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL REFERENCES workspace_channels(workspace_id),
    owner_id TEXT NOT NULL, name TEXT NOT NULL, purpose TEXT NOT NULL DEFAULT '',
    capabilities TEXT NOT NULL DEFAULT '[]', enrollment_id TEXT NOT NULL,
    state TEXT NOT NULL DEFAULT 'disabled', published INTEGER NOT NULL DEFAULT 0,
    revision INTEGER NOT NULL DEFAULT 0, expires_at TEXT, updated_at TEXT NOT NULL
);
CREATE INDEX channel_directory_workspace ON workspace_bot_directory(workspace_id,state);
CREATE TABLE channel_threads (
    id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL REFERENCES workspace_channels(workspace_id),
    principal_id TEXT NOT NULL, origin_bot_id TEXT, origin_run_id TEXT,
    state TEXT NOT NULL DEFAULT 'open', deadline TEXT NOT NULL,
    runs_used INTEGER NOT NULL DEFAULT 0, messages_used INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
CREATE TABLE channel_messages (
    id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL REFERENCES workspace_channels(workspace_id),
    thread_id TEXT NOT NULL REFERENCES channel_threads(id), seq INTEGER NOT NULL,
    sender_bot_id TEXT, sender_name TEXT NOT NULL, sender_run_id TEXT, principal_id TEXT NOT NULL,
    kind TEXT NOT NULL, recipient_id TEXT, recipient_enrollment TEXT, reply_to TEXT,
    body TEXT NOT NULL, request_key TEXT NOT NULL, digest TEXT NOT NULL, created_at TEXT NOT NULL,
    UNIQUE(workspace_id,request_key), UNIQUE(workspace_id,seq)
);
CREATE UNIQUE INDEX channel_one_reply ON channel_messages(reply_to) WHERE kind='reply';
CREATE TABLE channel_deliveries (
    id TEXT PRIMARY KEY, thread_id TEXT NOT NULL REFERENCES channel_threads(id),
    message_id TEXT REFERENCES channel_messages(id), target_bot_id TEXT NOT NULL,
    target_enrollment TEXT NOT NULL, source_bot_id TEXT, source_enrollment TEXT,
    source_run_id TEXT, state TEXT NOT NULL DEFAULT 'queued', reason TEXT,
    run_id TEXT UNIQUE, mode TEXT NOT NULL DEFAULT 'communication', depth INTEGER NOT NULL,
    continuation_id TEXT, created_at TEXT NOT NULL
);
CREATE UNIQUE INDEX channel_one_delivery ON channel_deliveries(message_id,target_enrollment) WHERE message_id IS NOT NULL;
CREATE INDEX channel_inbox ON channel_deliveries(state,target_bot_id,created_at);
CREATE TABLE channel_continuations (
    id TEXT PRIMARY KEY, thread_id TEXT NOT NULL REFERENCES channel_threads(id),
    bot_id TEXT NOT NULL, enrollment_id TEXT NOT NULL, source_run_id TEXT NOT NULL UNIQUE,
    requests TEXT NOT NULL, summary TEXT NOT NULL, wait_mode TEXT NOT NULL,
    run_mode TEXT NOT NULL, state TEXT NOT NULL DEFAULT 'waiting', created_at TEXT NOT NULL
);
CREATE TABLE channel_run_context (
    run_id TEXT PRIMARY KEY, thread_id TEXT NOT NULL REFERENCES channel_threads(id),
    request_message_id TEXT, depth INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE workspace_channel_events (
    workspace_id TEXT NOT NULL REFERENCES workspace_channels(workspace_id), seq INTEGER NOT NULL,
    kind TEXT NOT NULL, data TEXT NOT NULL, created_at TEXT NOT NULL, PRIMARY KEY(workspace_id,seq)
);
CREATE TABLE channel_read_cursors (
    workspace_id TEXT NOT NULL REFERENCES workspace_channels(workspace_id), principal_id TEXT NOT NULL,
    sequence INTEGER NOT NULL DEFAULT 0, PRIMARY KEY(workspace_id,principal_id)
);
CREATE TABLE channel_artifact_grants (
    id TEXT PRIMARY KEY, message_id TEXT NOT NULL REFERENCES channel_messages(id),
    workspace_id TEXT NOT NULL, blob_id TEXT NOT NULL, revision TEXT NOT NULL,
    published_by TEXT NOT NULL, revoked INTEGER NOT NULL DEFAULT 0,
    UNIQUE(message_id,blob_id)
);
CREATE TABLE channel_dispatch_checks (
    delivery_id TEXT PRIMARY KEY REFERENCES channel_deliveries(id), last_checked TEXT NOT NULL
);
ALTER TABLE channel_threads ADD COLUMN run_limit INTEGER NOT NULL DEFAULT 8;
ALTER TABLE channel_threads ADD COLUMN allowed_policy_id TEXT DEFAULT '*';
CREATE TABLE channel_automation_roots (
    kind TEXT NOT NULL, origin_id TEXT NOT NULL, thread_id TEXT NOT NULL REFERENCES channel_threads(id),
    PRIMARY KEY(kind,origin_id)
);
