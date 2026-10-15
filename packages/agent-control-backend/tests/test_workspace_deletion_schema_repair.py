"""Upgrade both deployed versions of 021 without losing admission markers."""

import sqlite3
from pathlib import Path

import pytest
from agentbot_control.db import Database
from agentbot_control.repositories.workspace_deletion_commands import commit
from agentbot_control.repositories.workspace_preview import preview
from agentbot_control.workspace_deletions.schemas import DeleteCommand

REPAIR = "022_workspace_deletion_repair.sql"


def deployed_database(path: Path, early: bool) -> None:
    database = Database(path)
    with database.transaction() as db:
        db.execute("INSERT INTO users VALUES ('owner','owner','hash','date')")
        db.execute("INSERT INTO workspaces(id,owner_id,name) VALUES ('team','owner','Team')")
        db.execute("INSERT INTO workspace_members VALUES ('team','owner','owner')")
        db.execute(
            "INSERT INTO bots(id,owner_id,name,framework,instructions,created_at,updated_at) VALUES ('aaaaaaaaaaaaaaaa','owner','Bot','microsoft','private','date','date')"
        )
        db.execute(
            "INSERT INTO bot_streams(bot_id,workspace_id) VALUES ('aaaaaaaaaaaaaaaa','team')"
        )
        db.execute(
            "INSERT INTO workspace_file_writers VALUES ('transfer','aaaaaaaaaaaaaaaa','date','staging-transfer-test','cleanup_pending')"
        )
        db.execute("DELETE FROM schema_migrations WHERE version=?", (REPAIR,))
        if early:
            db.execute("DROP TABLE workspace_deleted_operations")
            db.execute("ALTER TABLE workspace_file_writers DROP COLUMN staging_name")
            db.execute("ALTER TABLE workspace_file_writers DROP COLUMN state")
    database.close()


@pytest.mark.parametrize("early", [True, False])
def test_repair_preserves_markers_and_allows_deletion(tmp_path, early):
    path = tmp_path / "deployed.sqlite"
    deployed_database(path, early)
    database = Database(path)
    try:
        with database.transaction() as db:
            marker = db.execute("SELECT * FROM workspace_file_writers").fetchone()
            assert marker["state"] == ("active" if early else "cleanup_pending")
            assert marker["staging_name"] == (None if early else "staging-transfer-test")
            checked = preview(db, "owner", "team")
            assert [b.code for b in checked.blockers] == ["transfers_active"]
            db.execute("DELETE FROM workspace_file_writers")
            checked = preview(db, "owner", "team")
            command = DeleteCommand(
                request_id="delete-repaired",
                preview_digest=checked.preview_digest,
                confirm_name="Team",
            )
            result = commit(
                db, "owner", "team", command, "fingerprint", lambda: True, lambda _: None
            )
            assert result.counts["bots"] == 1
            assert db.execute("SELECT deleted_at FROM workspaces WHERE id='team'").fetchone()[0]
            assert not db.execute("PRAGMA foreign_key_check").fetchall()
        database.migrate()
        assert (
            database.connection.execute(
                "SELECT COUNT(*) FROM schema_migrations WHERE version=?", (REPAIR,)
            ).fetchone()[0]
            == 1
        )
    finally:
        database.close()


def test_repair_failure_rolls_back_columns_table_and_receipt(tmp_path, monkeypatch):
    path = tmp_path / "deployed.sqlite"
    deployed_database(path, early=True)
    original = Path.read_text

    def broken(source, *args, **kwargs):
        text = original(source, *args, **kwargs)
        return (
            text + "\nINSERT INTO missing_repair_table VALUES (1);"
            if source.name == REPAIR
            else text
        )

    with monkeypatch.context() as patch:
        patch.setattr(Path, "read_text", broken)
        with pytest.raises(sqlite3.OperationalError, match="missing_repair_table"):
            Database(path)
    with sqlite3.connect(path) as db:
        assert {r[1] for r in db.execute("PRAGMA table_info(workspace_file_writers)")} == {
            "id",
            "bot_id",
            "created_at",
        }
        assert not db.execute(
            "SELECT 1 FROM sqlite_master WHERE name='workspace_deleted_operations'"
        ).fetchone()
        assert not db.execute(
            "SELECT 1 FROM schema_migrations WHERE version=?", (REPAIR,)
        ).fetchone()
        assert db.execute("SELECT COUNT(*) FROM workspace_file_writers").fetchone()[0] == 1
