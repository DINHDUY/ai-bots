"""Durable receipts and local cleanup identities, independent of deleted bot rows."""

import json
import sqlite3

from agentbot_control.workspace_deletions.schemas import CleanupStatus, DeletionResult


def receipt(db: sqlite3.Connection, owner: str, request_id: str) -> sqlite3.Row | None:
    return db.execute(
        "SELECT * FROM workspace_deletions WHERE owner_id=? AND request_id=?",
        (owner, request_id),
    ).fetchone()


def result(db: sqlite3.Connection, row: sqlite3.Row) -> DeletionResult:
    pending = db.execute(
        "SELECT COUNT(*),COALESCE(SUM(size),0),MAX(attempts) FROM workspace_cleanup_items "
        "WHERE workspace_id=? AND state!='complete'",
        (row["workspace_id"],),
    ).fetchone()
    errors = [
        r[0]
        for r in db.execute(
            "SELECT DISTINCT error_code FROM workspace_cleanup_items "
            "WHERE workspace_id=? AND state!='complete' AND error_code IS NOT NULL",
            (row["workspace_id"],),
        )
    ]
    return DeletionResult(
        request_id=row["request_id"],
        workspace_id=row["workspace_id"],
        workspace_name=row["workspace_name"],
        deleted_at=row["deleted_at"],
        counts=json.loads(row["counts"]),
        retained=json.loads(row["retained"]),
        cleanup=CleanupStatus(
            state="complete" if not pending[0] else "needs_attention" if errors else "pending",
            remaining=pending[0],
            bytes_remaining=pending[1],
            errors=errors,
        ),
    )


def add_item(db: sqlite3.Connection, wid: str, kind: str, rid: str, size: int = 0) -> None:
    db.execute(
        "INSERT OR IGNORE INTO workspace_cleanup_items(workspace_id,kind,resource_id,size) "
        "VALUES (?,?,?,?)",
        (wid, kind, rid, size),
    )


def get(db, owner, request_id):
    from fastapi import HTTPException

    row = receipt(db, owner, request_id)
    if row is None:
        raise HTTPException(404, "Deletion receipt unavailable.")
    return result(db, row)


def history(db, owner, cursor):
    from agentbot_control.workspace_deletions.schemas import DeletionHistory

    records = db.execute(
        "SELECT * FROM workspace_deletions WHERE owner_id=? ORDER BY deleted_at DESC,request_id LIMIT 21 OFFSET ?",
        (owner, cursor),
    ).fetchall()
    return DeletionHistory(
        items=[result(db, r) for r in records[:20]],
        next_cursor=cursor + 20 if len(records) > 20 else None,
    )


def retry(db, owner, request_id):
    current = get(db, owner, request_id)
    db.execute(
        "UPDATE workspace_cleanup_items SET retry_at=0 WHERE workspace_id=? AND state!='complete'",
        (current.workspace_id,),
    )
    return current
