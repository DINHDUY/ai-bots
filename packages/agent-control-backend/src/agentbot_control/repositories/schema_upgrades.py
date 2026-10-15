"""Conditional SQLite schema steps executed inside their versioned migration."""

import sqlite3


def workspace_writer_columns(db: sqlite3.Connection) -> None:
    """Repair early 021 deployments without overwriting settled staging markers."""
    columns = {row[1] for row in db.execute("PRAGMA table_info(workspace_file_writers)")}
    additions = {"staging_name": "TEXT", "state": "TEXT NOT NULL DEFAULT 'active'"}
    for name, declaration in additions.items():
        if name not in columns:
            db.execute(f"ALTER TABLE workspace_file_writers ADD COLUMN {name} {declaration}")
