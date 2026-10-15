ALTER TABLE workspaces ADD COLUMN deleted_at TEXT;
CREATE TABLE workspace_deletions (
 owner_id TEXT NOT NULL REFERENCES users(id), request_id TEXT NOT NULL,
 workspace_id TEXT NOT NULL UNIQUE REFERENCES workspaces(id), fingerprint TEXT NOT NULL,
 workspace_name TEXT NOT NULL, counts TEXT NOT NULL, retained TEXT NOT NULL,
 deleted_at TEXT NOT NULL, PRIMARY KEY(owner_id,request_id)
);
CREATE TABLE workspace_deleted_bots (
 bot_id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL REFERENCES workspaces(id)
);
CREATE TABLE workspace_cleanup_items (
 workspace_id TEXT NOT NULL REFERENCES workspaces(id), kind TEXT NOT NULL,
 resource_id TEXT NOT NULL, size INTEGER NOT NULL DEFAULT 0,
 state TEXT NOT NULL DEFAULT 'pending', attempts INTEGER NOT NULL DEFAULT 0,
 retry_at REAL NOT NULL DEFAULT 0, error_code TEXT,
 PRIMARY KEY(workspace_id,kind,resource_id)
);
CREATE TABLE workspace_file_writers (
 id TEXT PRIMARY KEY, bot_id TEXT NOT NULL REFERENCES bots(id), created_at TEXT NOT NULL,
 staging_name TEXT, state TEXT NOT NULL DEFAULT 'active'
);
CREATE TRIGGER protect_personal_workspace BEFORE UPDATE OF deleted_at ON workspaces
 WHEN NEW.deleted_at IS NOT NULL AND OLD.id='personal_' || OLD.owner_id
 BEGIN SELECT RAISE(ABORT,'workspace_protected'); END;
CREATE TRIGGER protect_workspace_tombstone BEFORE UPDATE OF deleted_at ON workspaces
 WHEN OLD.deleted_at IS NOT NULL AND NEW.deleted_at IS NULL
 BEGIN SELECT RAISE(ABORT,'workspace_deleted'); END;

CREATE TRIGGER deleted_workspace_workspace_members_insert BEFORE INSERT ON workspace_members
 WHEN EXISTS(SELECT 1 FROM workspaces WHERE id=NEW.workspace_id AND deleted_at IS NOT NULL)
 BEGIN SELECT RAISE(ABORT,'workspace_deleted'); END;

CREATE TRIGGER deleted_workspace_workspace_members_move BEFORE UPDATE OF workspace_id ON workspace_members
 WHEN EXISTS(SELECT 1 FROM workspaces WHERE id=NEW.workspace_id AND deleted_at IS NOT NULL)
 BEGIN SELECT RAISE(ABORT,'workspace_deleted'); END;

CREATE TRIGGER deleted_workspace_bot_streams_insert BEFORE INSERT ON bot_streams
 WHEN EXISTS(SELECT 1 FROM workspaces WHERE id=NEW.workspace_id AND deleted_at IS NOT NULL)
 BEGIN SELECT RAISE(ABORT,'workspace_deleted'); END;

CREATE TRIGGER deleted_workspace_bot_streams_move BEFORE UPDATE OF workspace_id ON bot_streams
 WHEN EXISTS(SELECT 1 FROM workspaces WHERE id=NEW.workspace_id AND deleted_at IS NOT NULL)
 BEGIN SELECT RAISE(ABORT,'workspace_deleted'); END;

CREATE TRIGGER deleted_workspace_workspace_channels_insert BEFORE INSERT ON workspace_channels
 WHEN EXISTS(SELECT 1 FROM workspaces WHERE id=NEW.workspace_id AND deleted_at IS NOT NULL)
 BEGIN SELECT RAISE(ABORT,'workspace_deleted'); END;

CREATE TRIGGER deleted_workspace_workspace_channels_move BEFORE UPDATE OF workspace_id ON workspace_channels
 WHEN EXISTS(SELECT 1 FROM workspaces WHERE id=NEW.workspace_id AND deleted_at IS NOT NULL)
 BEGIN SELECT RAISE(ABORT,'workspace_deleted'); END;

CREATE TRIGGER deleted_workspace_workspace_bot_directory_insert BEFORE INSERT ON workspace_bot_directory
 WHEN EXISTS(SELECT 1 FROM workspaces WHERE id=NEW.workspace_id AND deleted_at IS NOT NULL)
 BEGIN SELECT RAISE(ABORT,'workspace_deleted'); END;

CREATE TRIGGER deleted_workspace_workspace_bot_directory_move BEFORE UPDATE OF workspace_id ON workspace_bot_directory
 WHEN EXISTS(SELECT 1 FROM workspaces WHERE id=NEW.workspace_id AND deleted_at IS NOT NULL)
 BEGIN SELECT RAISE(ABORT,'workspace_deleted'); END;

CREATE TRIGGER deleted_workspace_channel_threads_insert BEFORE INSERT ON channel_threads
 WHEN EXISTS(SELECT 1 FROM workspaces WHERE id=NEW.workspace_id AND deleted_at IS NOT NULL)
 BEGIN SELECT RAISE(ABORT,'workspace_deleted'); END;

CREATE TRIGGER deleted_workspace_channel_threads_move BEFORE UPDATE OF workspace_id ON channel_threads
 WHEN EXISTS(SELECT 1 FROM workspaces WHERE id=NEW.workspace_id AND deleted_at IS NOT NULL)
 BEGIN SELECT RAISE(ABORT,'workspace_deleted'); END;

CREATE TRIGGER deleted_workspace_channel_messages_insert BEFORE INSERT ON channel_messages
 WHEN EXISTS(SELECT 1 FROM workspaces WHERE id=NEW.workspace_id AND deleted_at IS NOT NULL)
 BEGIN SELECT RAISE(ABORT,'workspace_deleted'); END;

CREATE TRIGGER deleted_workspace_channel_messages_move BEFORE UPDATE OF workspace_id ON channel_messages
 WHEN EXISTS(SELECT 1 FROM workspaces WHERE id=NEW.workspace_id AND deleted_at IS NOT NULL)
 BEGIN SELECT RAISE(ABORT,'workspace_deleted'); END;

CREATE TRIGGER deleted_workspace_workspace_channel_events_insert BEFORE INSERT ON workspace_channel_events
 WHEN EXISTS(SELECT 1 FROM workspaces WHERE id=NEW.workspace_id AND deleted_at IS NOT NULL)
 BEGIN SELECT RAISE(ABORT,'workspace_deleted'); END;

CREATE TRIGGER deleted_workspace_workspace_channel_events_move BEFORE UPDATE OF workspace_id ON workspace_channel_events
 WHEN EXISTS(SELECT 1 FROM workspaces WHERE id=NEW.workspace_id AND deleted_at IS NOT NULL)
 BEGIN SELECT RAISE(ABORT,'workspace_deleted'); END;

CREATE TRIGGER deleted_workspace_channel_read_cursors_insert BEFORE INSERT ON channel_read_cursors
 WHEN EXISTS(SELECT 1 FROM workspaces WHERE id=NEW.workspace_id AND deleted_at IS NOT NULL)
 BEGIN SELECT RAISE(ABORT,'workspace_deleted'); END;

CREATE TRIGGER deleted_workspace_channel_read_cursors_move BEFORE UPDATE OF workspace_id ON channel_read_cursors
 WHEN EXISTS(SELECT 1 FROM workspaces WHERE id=NEW.workspace_id AND deleted_at IS NOT NULL)
 BEGIN SELECT RAISE(ABORT,'workspace_deleted'); END;

CREATE TRIGGER deleted_workspace_channel_enrollment_policies_insert BEFORE INSERT ON channel_enrollment_policies
 WHEN EXISTS(SELECT 1 FROM workspaces WHERE id=NEW.workspace_id AND deleted_at IS NOT NULL)
 BEGIN SELECT RAISE(ABORT,'workspace_deleted'); END;

CREATE TRIGGER deleted_workspace_channel_enrollment_policies_move BEFORE UPDATE OF workspace_id ON channel_enrollment_policies
 WHEN EXISTS(SELECT 1 FROM workspaces WHERE id=NEW.workspace_id AND deleted_at IS NOT NULL)
 BEGIN SELECT RAISE(ABORT,'workspace_deleted'); END;

CREATE TRIGGER deleted_workspace_channel_artifact_grants_insert BEFORE INSERT ON channel_artifact_grants
 WHEN EXISTS(SELECT 1 FROM workspaces WHERE id=NEW.workspace_id AND deleted_at IS NOT NULL)
 BEGIN SELECT RAISE(ABORT,'workspace_deleted'); END;

CREATE TRIGGER deleted_workspace_channel_artifact_grants_move BEFORE UPDATE OF workspace_id ON channel_artifact_grants
 WHEN EXISTS(SELECT 1 FROM workspaces WHERE id=NEW.workspace_id AND deleted_at IS NOT NULL)
 BEGIN SELECT RAISE(ABORT,'workspace_deleted'); END;

CREATE TRIGGER deleted_workspace_workspace_capture_retention_insert BEFORE INSERT ON workspace_capture_retention
 WHEN EXISTS(SELECT 1 FROM workspaces WHERE id=NEW.workspace_id AND deleted_at IS NOT NULL)
 BEGIN SELECT RAISE(ABORT,'workspace_deleted'); END;

CREATE TRIGGER deleted_workspace_workspace_capture_retention_move BEFORE UPDATE OF workspace_id ON workspace_capture_retention
 WHEN EXISTS(SELECT 1 FROM workspaces WHERE id=NEW.workspace_id AND deleted_at IS NOT NULL)
 BEGIN SELECT RAISE(ABORT,'workspace_deleted'); END;

CREATE TRIGGER deleted_workspace_workspace_computer_settings_insert BEFORE INSERT ON workspace_computer_settings
 WHEN EXISTS(SELECT 1 FROM workspaces WHERE id=NEW.workspace_id AND deleted_at IS NOT NULL)
 BEGIN SELECT RAISE(ABORT,'workspace_deleted'); END;

CREATE TRIGGER deleted_workspace_workspace_computer_settings_move BEFORE UPDATE OF workspace_id ON workspace_computer_settings
 WHEN EXISTS(SELECT 1 FROM workspaces WHERE id=NEW.workspace_id AND deleted_at IS NOT NULL)
 BEGIN SELECT RAISE(ABORT,'workspace_deleted'); END;

CREATE TRIGGER deleted_workspace_groups_insert BEFORE INSERT ON groups
 WHEN EXISTS(SELECT 1 FROM workspaces WHERE id=NEW.workspace_id AND deleted_at IS NOT NULL)
 BEGIN SELECT RAISE(ABORT,'workspace_deleted'); END;

CREATE TRIGGER deleted_workspace_groups_move BEFORE UPDATE OF workspace_id ON groups
 WHEN EXISTS(SELECT 1 FROM workspaces WHERE id=NEW.workspace_id AND deleted_at IS NOT NULL)
 BEGIN SELECT RAISE(ABORT,'workspace_deleted'); END;

CREATE TRIGGER deleted_workspace_routines_insert BEFORE INSERT ON routines
 WHEN EXISTS(SELECT 1 FROM workspaces WHERE id=NEW.workspace_id AND deleted_at IS NOT NULL)
 BEGIN SELECT RAISE(ABORT,'workspace_deleted'); END;

CREATE TRIGGER deleted_workspace_routines_move BEFORE UPDATE OF workspace_id ON routines
 WHEN EXISTS(SELECT 1 FROM workspaces WHERE id=NEW.workspace_id AND deleted_at IS NOT NULL)
 BEGIN SELECT RAISE(ABORT,'workspace_deleted'); END;

CREATE TRIGGER deleted_workspace_computer_sessions_insert BEFORE INSERT ON computer_sessions
 WHEN EXISTS(SELECT 1 FROM workspaces WHERE id=NEW.workspace_id AND deleted_at IS NOT NULL)
 BEGIN SELECT RAISE(ABORT,'workspace_deleted'); END;

CREATE TRIGGER deleted_workspace_computer_sessions_move BEFORE UPDATE OF workspace_id ON computer_sessions
 WHEN EXISTS(SELECT 1 FROM workspaces WHERE id=NEW.workspace_id AND deleted_at IS NOT NULL)
 BEGIN SELECT RAISE(ABORT,'workspace_deleted'); END;

CREATE TRIGGER deleted_workspace_lifecycle_operations_insert BEFORE INSERT ON lifecycle_operations
 WHEN EXISTS(SELECT 1 FROM workspaces WHERE id=NEW.workspace_id AND deleted_at IS NOT NULL)
 BEGIN SELECT RAISE(ABORT,'workspace_deleted'); END;

CREATE TRIGGER deleted_workspace_lifecycle_operations_move BEFORE UPDATE OF workspace_id ON lifecycle_operations
 WHEN EXISTS(SELECT 1 FROM workspaces WHERE id=NEW.workspace_id AND deleted_at IS NOT NULL)
 BEGIN SELECT RAISE(ABORT,'workspace_deleted'); END;

CREATE TRIGGER deleted_workspace_computer_provider_bindings_insert BEFORE INSERT ON computer_provider_bindings
 WHEN EXISTS(SELECT 1 FROM workspaces WHERE id=NEW.workspace_id AND deleted_at IS NOT NULL)
 BEGIN SELECT RAISE(ABORT,'workspace_deleted'); END;

CREATE TRIGGER deleted_workspace_computer_provider_bindings_move BEFORE UPDATE OF workspace_id ON computer_provider_bindings
 WHEN EXISTS(SELECT 1 FROM workspaces WHERE id=NEW.workspace_id AND deleted_at IS NOT NULL)
 BEGIN SELECT RAISE(ABORT,'workspace_deleted'); END;

CREATE TRIGGER deleted_bot_bot_streams BEFORE INSERT ON bot_streams
 WHEN EXISTS(SELECT 1 FROM workspace_deleted_bots WHERE bot_id=NEW.bot_id)
 BEGIN SELECT RAISE(ABORT,'workspace_deleted'); END;

CREATE TRIGGER deleted_bot_computer_sessions BEFORE INSERT ON computer_sessions
 WHEN EXISTS(SELECT 1 FROM workspace_deleted_bots WHERE bot_id=NEW.bot_id)
 BEGIN SELECT RAISE(ABORT,'workspace_deleted'); END;

CREATE TRIGGER deleted_bot_runs BEFORE INSERT ON runs
 WHEN EXISTS(SELECT 1 FROM workspace_deleted_bots WHERE bot_id=NEW.bot_id)
 BEGIN SELECT RAISE(ABORT,'workspace_deleted'); END;

CREATE TRIGGER deleted_bot_messages BEFORE INSERT ON messages
 WHEN EXISTS(SELECT 1 FROM workspace_deleted_bots WHERE bot_id=NEW.bot_id)
 BEGIN SELECT RAISE(ABORT,'workspace_deleted'); END;

CREATE TRIGGER deleted_bot_capture_records BEFORE INSERT ON capture_records
 WHEN EXISTS(SELECT 1 FROM workspace_deleted_bots WHERE bot_id=NEW.bot_id)
 BEGIN SELECT RAISE(ABORT,'workspace_deleted'); END;

CREATE TRIGGER deleted_bot_capture_storage BEFORE INSERT ON capture_storage
 WHEN EXISTS(SELECT 1 FROM workspace_deleted_bots WHERE bot_id=NEW.bot_id)
 BEGIN SELECT RAISE(ABORT,'workspace_deleted'); END;

CREATE TRIGGER deleted_bot_file_blobs BEFORE INSERT ON file_blobs
 WHEN EXISTS(SELECT 1 FROM workspace_deleted_bots WHERE bot_id=NEW.bot_id)
 BEGIN SELECT RAISE(ABORT,'workspace_deleted'); END;

CREATE TRIGGER deleted_bot_uploads BEFORE INSERT ON uploads
 WHEN EXISTS(SELECT 1 FROM workspace_deleted_bots WHERE bot_id=NEW.bot_id)
 BEGIN SELECT RAISE(ABORT,'workspace_deleted'); END;

CREATE TRIGGER deleted_bot_workspace_file_writers BEFORE INSERT ON workspace_file_writers
 WHEN EXISTS(SELECT 1 FROM workspace_deleted_bots WHERE bot_id=NEW.bot_id)
 BEGIN SELECT RAISE(ABORT,'workspace_deleted'); END;

CREATE TRIGGER deleted_bot_workspace_bot_directory BEFORE INSERT ON workspace_bot_directory
 WHEN EXISTS(SELECT 1 FROM workspace_deleted_bots WHERE bot_id=NEW.bot_id)
 BEGIN SELECT RAISE(ABORT,'workspace_deleted'); END;

CREATE TRIGGER deleted_bot_windows_bindings BEFORE INSERT ON windows_bindings
 WHEN EXISTS(SELECT 1 FROM workspace_deleted_bots WHERE bot_id=NEW.bot_id)
 BEGIN SELECT RAISE(ABORT,'workspace_deleted'); END;

CREATE TRIGGER deleted_bot_computer_provider_bindings BEFORE INSERT ON computer_provider_bindings
 WHEN EXISTS(SELECT 1 FROM workspace_deleted_bots WHERE bot_id=NEW.bot_id)
 BEGIN SELECT RAISE(ABORT,'workspace_deleted'); END;

CREATE TRIGGER deleted_bot_bot_tool_config BEFORE INSERT ON bot_tool_config
 WHEN EXISTS(SELECT 1 FROM workspace_deleted_bots WHERE bot_id=NEW.bot_id)
 BEGIN SELECT RAISE(ABORT,'workspace_deleted'); END;

CREATE TRIGGER deleted_bot_bot_tool_bindings BEFORE INSERT ON bot_tool_bindings
 WHEN EXISTS(SELECT 1 FROM workspace_deleted_bots WHERE bot_id=NEW.bot_id)
 BEGIN SELECT RAISE(ABORT,'workspace_deleted'); END;

CREATE TRIGGER deleted_bot_bot_compute_config BEFORE INSERT ON bot_compute_config
 WHEN EXISTS(SELECT 1 FROM workspace_deleted_bots WHERE bot_id=NEW.bot_id)
 BEGIN SELECT RAISE(ABORT,'workspace_deleted'); END;

CREATE TRIGGER deleted_bot_cloud_compute_config BEFORE INSERT ON cloud_compute_config
 WHEN EXISTS(SELECT 1 FROM workspace_deleted_bots WHERE bot_id=NEW.bot_id)
 BEGIN SELECT RAISE(ABORT,'workspace_deleted'); END;

CREATE TRIGGER deleted_bot_bot_autopilot BEFORE INSERT ON bot_autopilot
 WHEN EXISTS(SELECT 1 FROM workspace_deleted_bots WHERE bot_id=NEW.bot_id)
 BEGIN SELECT RAISE(ABORT,'workspace_deleted'); END;

CREATE TRIGGER deleted_bot_approval_policies BEFORE INSERT ON approval_policies
 WHEN EXISTS(SELECT 1 FROM workspace_deleted_bots WHERE bot_id=NEW.bot_id)
 BEGIN SELECT RAISE(ABORT,'workspace_deleted'); END;

CREATE TRIGGER deleted_bot_bots BEFORE INSERT ON bots
 WHEN EXISTS(SELECT 1 FROM workspace_deleted_bots WHERE bot_id=NEW.id)
 BEGIN SELECT RAISE(ABORT,'workspace_deleted'); END;

CREATE TABLE workspace_deleted_operations (
 workspace_id TEXT NOT NULL REFERENCES workspaces(id), id TEXT PRIMARY KEY, bot_id TEXT NOT NULL,
 request_id TEXT NOT NULL, fingerprint TEXT NOT NULL, session_id TEXT, operation TEXT NOT NULL, status TEXT NOT NULL, result TEXT
);
