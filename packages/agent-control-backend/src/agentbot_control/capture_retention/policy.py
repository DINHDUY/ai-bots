from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING

from fastapi import HTTPException

from agentbot_control.common import stamp
from agentbot_control.schemas import Conflict

if TYPE_CHECKING:
    from agentbot_control.capture_retention import CaptureRetention


def policy(self: CaptureRetention, db, wid):
    row = db.execute(
        "SELECT * FROM workspace_capture_retention WHERE workspace_id=?", (wid,)
    ).fetchone()
    if not row:
        raise KeyError(wid)
    return dict(row)


def usage(self: CaptureRetention, db, wid):
    rows = db.execute(
        "SELECT state,COUNT(*) n,COALESCE(SUM(size),0) bytes FROM capture_storage WHERE workspace_id=? AND state!='removed' GROUP BY state",
        (wid,),
    ).fetchall()
    usage = {r["state"]: dict(r) for r in rows}
    files = db.execute(
        "SELECT COALESCE(SUM(f.size),0) FROM file_blobs f JOIN bot_streams b ON b.bot_id=f.bot_id WHERE b.workspace_id=?",
        (wid,),
    ).fetchone()[0]
    return {
        "retained_count": usage.get("available", {}).get("n", 0),
        "screenshot_bytes": sum(r["bytes"] for r in rows),
        "pending_bytes": sum(r["bytes"] for r in rows if r["state"] == "pending_delete"),
        "reserved_bytes": sum(r["bytes"] for r in rows if r["state"] == "reserved"),
        "file_bytes": files,
        "shared_bytes": files + sum(r["bytes"] for r in rows),
    }


def thresholds(self: CaptureRetention, p):
    q = p["max_bytes"]
    return {
        "trigger_bytes": q * (100 - p["reserve_percent"]) // 100 if q else None,
        "target_bytes": q * p["cleanup_target_percent"] // 100 if q else None,
    }


def settings(self: CaptureRetention, wid):
    with self.store.transaction() as db:
        p = self.policy(db, wid)
        return {
            **p,
            **self.thresholds(p),
            "usage": self.usage(db, wid),
            "shared_limit_bytes": self.store.blob_limit,
        }


def validate(self: CaptureRetention, command):
    if command.max_bytes and command.max_bytes > self.store.blob_limit:
        raise HTTPException(
            422,
            f"Screenshot quota exceeds the shared workspace ceiling of {self.store.blob_limit} bytes. Increase WORKSPACE_BLOB_LIMIT_BYTES first.",
        )


def configure(self: CaptureRetention, wid, uid, command):
    self.validate(command)
    with self.store.transaction() as db:
        old = self.policy(db, wid)
        if old["revision"] != command.revision:
            raise Conflict("Retention settings changed. Reload before saving.")
        values = command.model_dump(exclude={"revision"})
        db.execute(
            "UPDATE workspace_capture_retention SET "
            + ",".join(f"{k}=?" for k in values)
            + ",revision=revision+1,updated_by=?,updated_at=?,cleanup_pending=1,target_bytes=NULL WHERE workspace_id=?",
            (*values.values(), uid, stamp(), wid),
        )
        # A shorter/longer age changes expiry even if no bytes are deleted yet.
        for row in db.execute(
            "SELECT bot_id FROM bot_streams WHERE workspace_id=?", (wid,)
        ).fetchall():
            self.changed(db, row[0], [], "policy")
    self.wake.set()
    return self.settings(wid)


def candidates(self: CaptureRetention, db, wid, p, incoming=0):
    """Streaming selection; callers bound mutation batches, preview only counts."""
    cutoff = (
        (self.clock() - timedelta(seconds=p["max_age_seconds"])).isoformat()
        if p["max_age_seconds"]
        else ""
    )
    count, _ = db.execute(
        "SELECT COUNT(*),COALESCE(SUM(size),0) FROM capture_storage WHERE workspace_id=? AND state='available'",
        (wid,),
    ).fetchone()
    usage = self.usage(db, wid)
    age_n, age_bytes = db.execute(
        "SELECT COUNT(*),COALESCE(SUM(s.size),0) FROM capture_storage s JOIN capture_records c ON c.id=s.id WHERE s.workspace_id=? AND s.state='available' AND c.created_at<=?",
        (wid, cutoff),
    ).fetchone()
    excess = (
        max(0, count - age_n + (1 if incoming else 0) - p["max_count"]) if p["max_count"] else 0
    )
    count_bytes = db.execute(
        "SELECT COALESCE(SUM(size),0) FROM (SELECT s.size FROM capture_storage s JOIN capture_records c ON c.id=s.id WHERE s.workspace_id=? AND s.state='available' AND c.created_at>? ORDER BY s.sequence LIMIT ?)",
        (wid, cutoff, excess),
    ).fetchone()[0]
    projected = usage["screenshot_bytes"] - age_bytes - count_bytes + incoming
    thresholds = self.thresholds(p)
    target = p.get("target_bytes")
    if thresholds["trigger_bytes"] and projected >= thresholds["trigger_bytes"]:
        target = thresholds["target_bytes"]
    needs_space = (target is not None and projected > target) or projected + usage[
        "file_bytes"
    ] > self.store.blob_limit
    if not age_n and not excess and not needs_space:
        return
    # Retire expired rows first, then count, then space, all oldest first.
    query = "SELECT s.*,c.created_at AS recorded_at FROM capture_storage s JOIN capture_records c ON c.id=s.id WHERE s.workspace_id=? AND s.state='available' ORDER BY s.sequence"
    remaining_excess = excess
    remaining_age = age_n
    for row in db.execute(query, (wid,)):
        if row["recorded_at"] <= cutoff:
            remaining_age -= 1
            yield row, "age", target
            continue
        reason = None
        if remaining_excess:
            remaining_excess -= 1
            yield row, "count", target
            continue
        elif target is not None and projected > target:
            reason = "quota"
        elif projected + usage["file_bytes"] > self.store.blob_limit:
            reason = "workspace_quota"
        if reason:
            projected -= row["size"]
            yield row, reason, target
        elif not remaining_age:
            break


def preview(self: CaptureRetention, wid, command):
    self.validate(command)
    with self.store.transaction() as db:
        n = size = 0
        for row, _, _ in self.candidates(db, wid, command.model_dump()):
            n += 1
            size += row["size"]
        return dict(
            remove_count=n,
            remove_bytes=size,
            **self.thresholds(command.model_dump()),
        )
