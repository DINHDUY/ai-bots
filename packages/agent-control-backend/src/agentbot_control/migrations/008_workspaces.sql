CREATE TABLE workspaces_new (id TEXT PRIMARY KEY, owner_id TEXT NOT NULL REFERENCES users(id), name TEXT NOT NULL);
INSERT INTO workspaces_new SELECT * FROM workspaces;
DROP TABLE workspaces;
ALTER TABLE workspaces_new RENAME TO workspaces;
CREATE TABLE execution_grants (bot_id TEXT REFERENCES bots(id) ON DELETE CASCADE, user_id TEXT REFERENCES users(id), PRIMARY KEY(bot_id,user_id));
CREATE TABLE share_grants (id TEXT PRIMARY KEY, bot_id TEXT REFERENCES bots(id) ON DELETE CASCADE, session_id TEXT, recipient_id TEXT REFERENCES users(id), surfaces TEXT NOT NULL, artifacts TEXT NOT NULL, expires_at TEXT NOT NULL, revoked INTEGER NOT NULL DEFAULT 0);
CREATE TABLE user_preferences (user_id TEXT PRIMARY KEY REFERENCES users(id), revision INTEGER NOT NULL, data TEXT NOT NULL);
CREATE TABLE notifications (id TEXT PRIMARY KEY, user_id TEXT REFERENCES users(id), bot_id TEXT REFERENCES bots(id) ON DELETE CASCADE, event_id TEXT NOT NULL, kind TEXT NOT NULL, created_at TEXT NOT NULL, read INTEGER NOT NULL DEFAULT 0, UNIQUE(user_id,event_id));
CREATE VIRTUAL TABLE search_index USING fts5(resource_id UNINDEXED,bot_id UNINDEXED,kind UNINDEXED,title,content);
