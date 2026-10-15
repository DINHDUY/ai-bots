CREATE TABLE bot_tool_config (bot_id TEXT PRIMARY KEY REFERENCES bots(id) ON DELETE CASCADE, revision INTEGER NOT NULL, format_version INTEGER NOT NULL DEFAULT 1, updated_by TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE bot_tool_bindings (id TEXT PRIMARY KEY, bot_id TEXT NOT NULL REFERENCES bots(id) ON DELETE CASCADE, library_id TEXT NOT NULL, version TEXT NOT NULL, tool_id TEXT NOT NULL, configuration TEXT NOT NULL, revision INTEGER NOT NULL DEFAULT 1, enabled INTEGER NOT NULL DEFAULT 1, provenance TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE UNIQUE INDEX active_tool_binding ON bot_tool_bindings(bot_id,library_id,tool_id,configuration) WHERE enabled=1;
CREATE TABLE run_tool_bindings (run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE, binding_id TEXT NOT NULL, binding_revision INTEGER NOT NULL, manifest_digest TEXT NOT NULL, snapshot TEXT NOT NULL, PRIMARY KEY(run_id,binding_id));
ALTER TABLE actions ADD COLUMN tool_binding_id TEXT;
ALTER TABLE actions ADD COLUMN tool_binding_revision INTEGER;
ALTER TABLE actions ADD COLUMN tool_manifest_digest TEXT;
