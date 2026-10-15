CREATE TABLE auth_limits (
    key TEXT PRIMARY KEY,
    attempts INTEGER NOT NULL,
    expires REAL NOT NULL
);
