CREATE TABLE macos_devices (
 id TEXT PRIMARY KEY, owner_id TEXT NOT NULL REFERENCES users(id), name TEXT NOT NULL,
 token_hash TEXT NOT NULL UNIQUE, created_at TEXT NOT NULL, revoked_at TEXT
);
CREATE TABLE macos_enrollments (
 id TEXT PRIMARY KEY, owner_id TEXT NOT NULL REFERENCES users(id), secret_hash TEXT NOT NULL UNIQUE,
 expires_at TEXT NOT NULL, consumed_at TEXT, request_id TEXT NOT NULL,
 UNIQUE(owner_id,request_id)
);
CREATE TABLE macos_compute_config (
 bot_id TEXT PRIMARY KEY REFERENCES bots(id) ON DELETE CASCADE,
 device_id TEXT NOT NULL REFERENCES macos_devices(id), revision INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE macos_bindings (
 session_id TEXT PRIMARY KEY, bot_id TEXT NOT NULL,
 device_id TEXT NOT NULL REFERENCES macos_devices(id), generation INTEGER NOT NULL,
 active INTEGER NOT NULL DEFAULT 1
);
CREATE UNIQUE INDEX one_macos_binding ON macos_bindings(device_id) WHERE active=1;
CREATE TABLE macos_task_links (
 owner_id TEXT NOT NULL REFERENCES users(id), producer TEXT NOT NULL, task_id TEXT NOT NULL,
 request_id TEXT NOT NULL, bot_id TEXT NOT NULL, device_id TEXT NOT NULL REFERENCES macos_devices(id),
 run_id TEXT NOT NULL, input_digest TEXT NOT NULL, deadline REAL NOT NULL,
 PRIMARY KEY(owner_id,producer,task_id), UNIQUE(owner_id,request_id)
);
CREATE TRIGGER macos_config_active_workspace BEFORE INSERT ON macos_compute_config
WHEN EXISTS(SELECT 1 FROM bot_streams s JOIN workspaces w ON w.id=s.workspace_id WHERE s.bot_id=NEW.bot_id AND w.deleted_at IS NOT NULL)
BEGIN SELECT RAISE(ABORT,'workspace_deleted'); END;
CREATE TRIGGER macos_binding_active_workspace BEFORE INSERT ON macos_bindings
WHEN EXISTS(SELECT 1 FROM bot_streams s JOIN workspaces w ON w.id=s.workspace_id WHERE s.bot_id=NEW.bot_id AND w.deleted_at IS NOT NULL)
BEGIN SELECT RAISE(ABORT,'workspace_deleted'); END;

