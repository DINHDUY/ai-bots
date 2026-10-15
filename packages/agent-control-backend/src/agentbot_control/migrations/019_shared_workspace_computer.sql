DROP TRIGGER IF EXISTS remove_bot_computer_control;
CREATE TABLE computer_sessions_new (
 id TEXT PRIMARY KEY,
 bot_id TEXT REFERENCES bots(id) ON DELETE CASCADE,
 workspace_id TEXT REFERENCES workspaces(id),
 generation INTEGER NOT NULL,
 status TEXT NOT NULL,
 created_at TEXT NOT NULL,
 updated_at TEXT NOT NULL,
 CHECK ((bot_id IS NULL) != (workspace_id IS NULL)),
 UNIQUE (bot_id, generation),
 UNIQUE (workspace_id, generation)
);
INSERT INTO computer_sessions_new (id, bot_id, generation, status, created_at, updated_at)
 SELECT id, bot_id, generation, status, created_at, updated_at FROM computer_sessions;
DROP TABLE computer_sessions;
ALTER TABLE computer_sessions_new RENAME TO computer_sessions;
CREATE UNIQUE INDEX one_computer ON computer_sessions(bot_id) WHERE status != 'closed' AND bot_id IS NOT NULL;
CREATE UNIQUE INDEX one_workspace_computer ON computer_sessions(workspace_id) WHERE bot_id IS NULL AND status != 'closed';

CREATE TABLE lifecycle_operations_new (
 id TEXT PRIMARY KEY,
 bot_id TEXT REFERENCES bots(id) ON DELETE CASCADE,
 workspace_id TEXT REFERENCES workspaces(id),
 request_id TEXT NOT NULL,
 fingerprint TEXT NOT NULL,
 session_id TEXT,
 operation TEXT NOT NULL,
 status TEXT NOT NULL,
 result TEXT,
 created_at TEXT NOT NULL,
 CHECK ((bot_id IS NULL) != (workspace_id IS NULL))
);
INSERT INTO lifecycle_operations_new (
 id, bot_id, request_id, fingerprint, session_id, operation, status, result, created_at
)
 SELECT id, bot_id, request_id, fingerprint, session_id, operation, status, result, created_at
 FROM lifecycle_operations;
DROP TABLE lifecycle_operations;
ALTER TABLE lifecycle_operations_new RENAME TO lifecycle_operations;
CREATE UNIQUE INDEX lifecycle_bot_request ON lifecycle_operations(bot_id, request_id) WHERE bot_id IS NOT NULL;
CREATE UNIQUE INDEX lifecycle_workspace_request ON lifecycle_operations(workspace_id, request_id) WHERE workspace_id IS NOT NULL;

CREATE TABLE workspace_computer_settings (
 workspace_id TEXT PRIMARY KEY REFERENCES workspaces(id),
 mode TEXT NOT NULL DEFAULT 'per_bot',
 provider TEXT NOT NULL DEFAULT 'docker',
 profile_id TEXT REFERENCES compute_profiles(id),
 ownership TEXT NOT NULL DEFAULT 'attached',
 revision INTEGER NOT NULL DEFAULT 0,
 updated_by TEXT,
 updated_at TEXT NOT NULL
);
CREATE TABLE workspace_computer_receipts (
 workspace_id TEXT NOT NULL REFERENCES workspaces(id),
 request_id TEXT NOT NULL,
 fingerprint TEXT NOT NULL,
 response TEXT NOT NULL,
 PRIMARY KEY (workspace_id, request_id)
);
ALTER TABLE computer_provider_bindings ADD COLUMN workspace_id TEXT REFERENCES workspaces(id);
ALTER TABLE cloud_operation_state ADD COLUMN workspace_id TEXT;
CREATE UNIQUE INDEX one_cloud_workspace ON computer_provider_bindings(workspace_id) WHERE active=1 AND workspace_id IS NOT NULL;
CREATE TRIGGER remove_bot_computer_control BEFORE DELETE ON bots BEGIN
 DELETE FROM recordings WHERE bot_id=OLD.id;
 DELETE FROM terminals WHERE bot_id=OLD.id;
 DELETE FROM control_leases WHERE bot_id=OLD.id;
 DELETE FROM computer_control WHERE session_id IN (SELECT id FROM computer_sessions WHERE bot_id=OLD.id);
 DELETE FROM computer_retention WHERE session_id IN (SELECT id FROM computer_sessions WHERE bot_id=OLD.id);
END;
