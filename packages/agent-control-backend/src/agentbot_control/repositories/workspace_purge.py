"""Atomic catalog removal; physical files are handled only after commit."""

import json
import sqlite3

from agentbot_control.common import packed
from agentbot_control.repositories.workspace_deletions import add_item
from agentbot_control.repositories.workspace_scope import BINDINGS, BOTS, CONTENT
from agentbot_control.repositories.workspaces import personal


def repair_preferences(db: sqlite3.Connection, wid: str, bot_ids: set[str]) -> None:
    for row in db.execute("SELECT * FROM user_preferences").fetchall():
        data = json.loads(row["data"])
        before = packed(data)
        if data.get("workspace_id") == wid:
            data["workspace_id"] = personal(db, row["user_id"])
        data["order"] = [bid for bid in data.get("order", []) if bid not in bot_ids]
        for key in ("folders", "read_cursors"):
            data[key] = {
                bid: value for bid, value in data.get(key, {}).items() if bid not in bot_ids
            }
        if packed(data) != before:
            db.execute(
                "UPDATE user_preferences SET data=?,revision=revision+1 WHERE user_id=?",
                (packed(data), row["user_id"]),
            )


def purge(db: sqlite3.Connection, wid: str, now: str) -> list[str]:
    bot_ids = [r[0] for r in db.execute(BOTS, (wid,))]
    for row in db.execute(f"SELECT id,size FROM file_blobs WHERE bot_id IN ({BOTS})", (wid,)):
        add_item(db, wid, "artifact", row["id"], row["size"])
    for row in db.execute(
        "SELECT id,size FROM capture_storage WHERE workspace_id=? AND state!='removed'", (wid,)
    ):
        add_item(db, wid, "capture", row["id"], row["size"])
    for bid in bot_ids:
        add_item(db, wid, "session", bid)
        db.execute("INSERT INTO workspace_deleted_bots VALUES (?,?)", (bid, wid))
    # Inactive provider identities survive removal and remain owner-recoverable.
    db.execute(f"DELETE FROM cloud_enrollments WHERE binding_id IN ({BINDINGS})", (wid, wid, wid))
    db.execute(
        f"UPDATE cloud_machine_credentials SET revoked_at=COALESCE(revoked_at,?) WHERE binding_id IN ({BINDINGS})",
        (now, wid, wid, wid),
    )
    db.execute("UPDATE compute_profiles SET enabled=0 WHERE workspace_id=?", (wid,))
    # Preserve per-bot lifecycle receipts as historical evidence before their cascade.
    db.execute(
        f"INSERT INTO workspace_deleted_operations SELECT ?,id,bot_id,request_id,fingerprint,session_id,operation,status,result FROM lifecycle_operations WHERE bot_id IN ({BOTS})",
        (wid, wid),
    )
    repair_preferences(db, wid, set(bot_ids))
    db.execute("UPDATE workspaces SET deleted_at=? WHERE id=?", (now, wid))
    for table, where in CONTENT:
        db.execute(f"DELETE FROM {table} WHERE {where}", (wid,))
    # Both per-bot and shared sessions have non-cascading control dependencies.
    for table in ("terminals", "recordings", "control_leases"):
        db.execute(f"DELETE FROM {table} WHERE bot_id IN ({BOTS})", (wid,))
    for table in ("computer_control", "computer_retention"):
        db.execute(
            f"DELETE FROM {table} WHERE session_id IN (SELECT id FROM computer_sessions WHERE workspace_id=? OR bot_id IN ({BOTS}))",
            (wid, wid),
        )
    db.execute(f"DELETE FROM bots WHERE id IN ({BOTS})", (wid,))
    # Shared computers have no bot parent; remove their closed control dependencies.
    for table in ("control_leases", "computer_control", "computer_retention"):
        db.execute(
            f"DELETE FROM {table} WHERE session_id IN (SELECT id FROM computer_sessions WHERE workspace_id=?)",
            (wid,),
        )
    db.execute("DELETE FROM computer_sessions WHERE workspace_id=?", (wid,))
    db.execute(
        "UPDATE capture_storage SET state='pending_delete',reason='workspace_deleted',removed_at=? WHERE workspace_id=? AND state!='removed'",
        (now, wid),
    )
    return bot_ids
