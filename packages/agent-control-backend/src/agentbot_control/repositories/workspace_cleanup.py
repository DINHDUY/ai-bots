"""Durable cleanup and transfer records; no filesystem effects."""

from time import time

from agentbot_control.db import Database


class CleanupRecords:
    def __init__(self, database: Database):
        self.database = database

    def staging(self):
        with self.database.transaction(write=False) as db:
            return db.execute(
                "SELECT id,staging_name FROM workspace_file_writers WHERE state='cleanup_pending' LIMIT 50"
            ).fetchall()

    def staged_removed(self, token):
        with self.database.transaction() as db:
            db.execute(
                "DELETE FROM workspace_file_writers WHERE id=? AND state='cleanup_pending'",
                (token,),
            )

    def pending(self):
        with self.database.transaction(write=False) as db:
            return db.execute(
                "SELECT * FROM workspace_cleanup_items WHERE state!='complete' AND retry_at<=? ORDER BY workspace_id,kind,resource_id LIMIT 50",
                (time(),),
            ).fetchall()

    def settled(self, row, error):
        with self.database.transaction() as db:
            db.execute(
                "UPDATE workspace_cleanup_items SET state=?,attempts=attempts+1,retry_at=?,error_code=? WHERE workspace_id=? AND kind=? AND resource_id=?",
                (
                    "pending" if error else "complete",
                    time() + min(300, 2 ** min(row["attempts"] + 1, 8)) if error else 0,
                    error,
                    row["workspace_id"],
                    row["kind"],
                    row["resource_id"],
                ),
            )
            if not error and row["kind"] == "capture":
                db.execute("DELETE FROM capture_storage WHERE id=?", (row["resource_id"],))


def is_deleted(database: Database, wid: str) -> bool:
    with database.transaction(write=False) as db:
        return (
            db.execute(
                "SELECT 1 FROM workspaces WHERE id=? AND deleted_at IS NOT NULL", (wid,)
            ).fetchone()
            is not None
        )


def recovery_workspace(database: Database, wid: str):
    with database.transaction(write=False) as db:
        return db.execute(
            "SELECT owner_id,deleted_at FROM workspaces WHERE id=?", (wid,)
        ).fetchone()


def recovery_binding(db, binding, wid):
    return (
        binding["workspace_id"] == wid
        or (
            db.execute(
                "SELECT 1 FROM workspace_deleted_bots WHERE bot_id=? AND workspace_id=?",
                (binding["bot_id"], wid),
            ).fetchone()
            is not None
        )
        or (
            db.execute(
                "SELECT 1 FROM compute_profiles WHERE id=? AND workspace_id=?",
                (binding["profile_id"], wid),
            ).fetchone()
            is not None
        )
    )
