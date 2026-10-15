"""The control plane keeps one connection and can open a pre-refactor database."""

import sqlite3

from agentbot_control.db import Database
from agentbot_control.event_store import EventStore
from agentbot_control.store import Catalog


def test_catalog_and_event_store_share_one_connection(tmp_path):
    path = tmp_path / "control.sqlite"
    catalog = Catalog(path, "test-secret")
    store = EventStore(path, db=catalog.db)
    assert store.db is catalog.db.connection
    assert store.lock is catalog.db.lock
    with store.transaction() as db:
        assert db.execute(
            "SELECT 1 FROM schema_migrations WHERE version='000_catalog.sql'"
        ).fetchone()


def test_pre_refactor_database_keeps_tables_and_migration_history(tmp_path):
    path = tmp_path / "control.sqlite"
    old = sqlite3.connect(path)
    old.executescript(
        """
        CREATE TABLE users (
            id TEXT PRIMARY KEY,
            username TEXT NOT NULL,
            password_hash TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE bots (
            id TEXT PRIMARY KEY,
            owner_id TEXT NOT NULL,
            name TEXT NOT NULL,
            framework TEXT NOT NULL,
            instructions TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE schema_migrations (
            version TEXT PRIMARY KEY,
            applied_at TEXT NOT NULL
        );
        INSERT INTO users VALUES ('user1', 'ada', 'hash', '2026-01-01T00:00:00');
        """
    )
    old.commit()
    # Mark the event migrations applied only after running them, as the old process did.
    from pathlib import Path

    root = Path(__file__).resolve().parents[1] / "src" / "agentbot_control" / "migrations"
    for migration in sorted(root.glob("*.sql")):
        if migration.name == "000_catalog.sql":
            continue
        old.executescript(migration.read_text(encoding="utf-8-sig"))
        old.execute(
            "INSERT INTO schema_migrations VALUES (?, ?)",
            (migration.name, "2026-01-01T00:00:00"),
        )
    old.commit()
    before = {
        row[0] for row in old.execute("SELECT version FROM schema_migrations")
    }
    old.close()

    database = Database(path)
    versions = {
        row[0]
        for row in database.connection.execute("SELECT version FROM schema_migrations")
    }
    assert before <= versions
    assert "000_catalog.sql" in versions
    columns = {row[1] for row in database.connection.execute("PRAGMA table_info(bots)")}
    assert {"credential_id", "model", "default_prompt"} <= columns
    owner = database.connection.execute(
        "SELECT username FROM users WHERE id='user1'"
    ).fetchone()[0]
    assert owner == "ada"
    database.close()
