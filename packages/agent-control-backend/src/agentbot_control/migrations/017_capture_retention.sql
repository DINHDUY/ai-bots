CREATE TABLE workspace_capture_retention (
 workspace_id TEXT PRIMARY KEY REFERENCES workspaces(id) ON DELETE CASCADE,
 revision INTEGER NOT NULL DEFAULT 1,
 max_count INTEGER, max_bytes INTEGER,
 reserve_percent INTEGER NOT NULL DEFAULT 25,
 cleanup_target_percent INTEGER NOT NULL DEFAULT 50,
 max_age_seconds INTEGER DEFAULT 604800,
 updated_by TEXT, updated_at TEXT,
 cleanup_pending INTEGER NOT NULL DEFAULT 0,
 target_bytes INTEGER, last_cleanup_at TEXT, last_error TEXT
);
INSERT INTO workspace_capture_retention(workspace_id) SELECT id FROM workspaces;
CREATE TRIGGER capture_policy_workspace AFTER INSERT ON workspaces BEGIN
 INSERT OR IGNORE INTO workspace_capture_retention(workspace_id) VALUES (NEW.id);
END;
-- Independent ledger survives bot/catalog cascades until bytes are reclaimed.
CREATE TABLE capture_storage (
 sequence INTEGER PRIMARY KEY AUTOINCREMENT,
 id TEXT NOT NULL UNIQUE, bot_id TEXT NOT NULL, workspace_id TEXT NOT NULL,
 size INTEGER NOT NULL, created_at TEXT NOT NULL,
 state TEXT NOT NULL CHECK(state IN ('reserved','available','pending_delete','removed')),
 reason TEXT, removed_at TEXT, attempts INTEGER NOT NULL DEFAULT 0,
 retry_at REAL NOT NULL DEFAULT 0
);
INSERT INTO capture_storage(id,bot_id,workspace_id,size,created_at,state)
 SELECT c.id,c.bot_id,b.workspace_id,c.size,c.created_at,'available'
 FROM capture_records c JOIN bot_streams b ON b.bot_id=c.bot_id ORDER BY c.created_at,c.id;
CREATE INDEX capture_storage_workspace_order ON capture_storage(workspace_id,state,sequence);
CREATE INDEX capture_storage_bot_order ON capture_storage(bot_id,state,sequence);
CREATE INDEX capture_storage_cleanup ON capture_storage(state,retry_at);
ALTER TABLE bot_streams ADD COLUMN captures_revision INTEGER NOT NULL DEFAULT 0;
CREATE TRIGGER capture_storage_insert AFTER INSERT ON capture_records BEGIN
 INSERT OR IGNORE INTO capture_storage(id,bot_id,workspace_id,size,created_at,state)
 SELECT NEW.id,NEW.bot_id,workspace_id,NEW.size,NEW.created_at,'available'
 FROM bot_streams WHERE bot_id=NEW.bot_id;
 UPDATE capture_storage SET state='available' WHERE id=NEW.id AND state='reserved';
END;
CREATE TRIGGER capture_storage_delete AFTER DELETE ON capture_records BEGIN
 UPDATE capture_storage SET state='pending_delete',reason=COALESCE(reason,'removed'),removed_at=COALESCE(removed_at,strftime('%Y-%m-%dT%H:%M:%f+00:00','now'))
 WHERE id=OLD.id AND state!='removed';
END;
