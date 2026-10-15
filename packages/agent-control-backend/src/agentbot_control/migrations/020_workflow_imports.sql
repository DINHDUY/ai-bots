CREATE TABLE workflow_import_receipts (
 owner_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 request_id TEXT NOT NULL,
 fingerprint TEXT NOT NULL,
 parser_version TEXT NOT NULL,
 workspace_id TEXT NOT NULL,
 result TEXT NOT NULL,
 created_at TEXT NOT NULL,
 PRIMARY KEY (owner_id, request_id)
);
