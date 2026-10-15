-- Some development deployments recorded migration 021 before its final additions.
-- Writer columns are added conditionally by repositories.schema_upgrades in the
-- same transaction, preserving installations that already have those columns.
CREATE TABLE IF NOT EXISTS workspace_deleted_operations (
 workspace_id TEXT NOT NULL REFERENCES workspaces(id), id TEXT PRIMARY KEY, bot_id TEXT NOT NULL,
 request_id TEXT NOT NULL, fingerprint TEXT NOT NULL, session_id TEXT, operation TEXT NOT NULL, status TEXT NOT NULL, result TEXT
);
