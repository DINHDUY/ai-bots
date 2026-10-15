-- Keep cloud inventory and cleanup after deletion of catalog/session rows.
CREATE TABLE compute_profiles (
 id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL, provider TEXT NOT NULL,
 name TEXT NOT NULL, revision INTEGER NOT NULL, config TEXT NOT NULL, enabled INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE cloud_compute_config (
 bot_id TEXT PRIMARY KEY REFERENCES bots(id) ON DELETE CASCADE,
 provider TEXT NOT NULL, profile_id TEXT REFERENCES compute_profiles(id), revision INTEGER NOT NULL,
 ownership TEXT NOT NULL DEFAULT 'attached'
);
CREATE TABLE compute_management_grants (
 bot_id TEXT NOT NULL REFERENCES bots(id) ON DELETE CASCADE, user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 PRIMARY KEY(bot_id,user_id)
);
CREATE TABLE computer_provider_bindings (
 id TEXT PRIMARY KEY, bot_id TEXT, owner_id TEXT NOT NULL, session_id TEXT, generation INTEGER NOT NULL DEFAULT 0,
 provider TEXT NOT NULL, profile_id TEXT NOT NULL, profile_snapshot TEXT NOT NULL,
 resource_id TEXT NOT NULL, ownership TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1,
 verified_owner TEXT, storage_ref TEXT NOT NULL, host_key TEXT, boot_id TEXT, container_id TEXT, writer_epoch INTEGER NOT NULL DEFAULT 0,
 status TEXT NOT NULL DEFAULT 'registered', observed_state TEXT, observed_at TEXT,
 cleanup_state TEXT NOT NULL DEFAULT 'none', created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE UNIQUE INDEX one_cloud_host ON computer_provider_bindings(resource_id COLLATE NOCASE) WHERE active=1;
CREATE UNIQUE INDEX one_cloud_bot ON computer_provider_bindings(bot_id) WHERE active=1;
CREATE TABLE cloud_enrollments (
 id TEXT PRIMARY KEY, binding_id TEXT NOT NULL, secret_hash TEXT NOT NULL UNIQUE,
 host_key TEXT NOT NULL, expires_at TEXT NOT NULL, consumed_at TEXT, created_at TEXT NOT NULL
);
CREATE TABLE cloud_machine_credentials (
 id TEXT PRIMARY KEY, binding_id TEXT NOT NULL, token_hash TEXT NOT NULL UNIQUE,
 expires_at TEXT NOT NULL, revoked_at TEXT, created_at TEXT NOT NULL
);
CREATE TABLE cloud_operation_state (
 operation_id TEXT PRIMARY KEY, binding_id TEXT NOT NULL, bot_id TEXT, actor_id TEXT NOT NULL,
 operation TEXT NOT NULL, phase TEXT NOT NULL, target_resource_id TEXT NOT NULL, deadline TEXT NOT NULL,
 attempts INTEGER NOT NULL DEFAULT 0, next_poll TEXT NOT NULL, submitted_at TEXT, correlation_id TEXT,
 continuation_sealed TEXT, error_code TEXT, detail TEXT, inventory TEXT NOT NULL DEFAULT '{}',
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE UNIQUE INDEX one_cloud_operation ON cloud_operation_state(binding_id)
 WHERE phase NOT IN ('completed','failed','outcome_unknown');
CREATE TABLE cloud_operation_receipts (
 bot_id TEXT NOT NULL, request_id TEXT NOT NULL, fingerprint TEXT NOT NULL, operation_id TEXT NOT NULL,
 PRIMARY KEY(bot_id,request_id)
);
CREATE TABLE cloud_resource_inventory (
 binding_id TEXT NOT NULL, resource_id TEXT NOT NULL, kind TEXT NOT NULL,
 operation_id TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'reserved',
 PRIMARY KEY(binding_id,resource_id)
);
-- Older computer control tables predate catalog cascade deletion.
CREATE TRIGGER remove_bot_computer_control BEFORE DELETE ON bots BEGIN
 DELETE FROM recordings WHERE bot_id=OLD.id;
 DELETE FROM terminals WHERE bot_id=OLD.id;
 DELETE FROM control_leases WHERE bot_id=OLD.id;
 DELETE FROM computer_control WHERE session_id IN (SELECT id FROM computer_sessions WHERE bot_id=OLD.id);
 DELETE FROM computer_retention WHERE session_id IN (SELECT id FROM computer_sessions WHERE bot_id=OLD.id);
END;
