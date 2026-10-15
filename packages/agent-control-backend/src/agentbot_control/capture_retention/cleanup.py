from __future__ import annotations

import asyncio
import re
from datetime import timedelta
from typing import TYPE_CHECKING

from agentbot_control.capture_retention import BATCH
from agentbot_control.common import stamp
from agentbot_control.repositories.workspace_cleanup import is_deleted

if TYPE_CHECKING:
    from agentbot_control.capture_retention import CaptureRetention


def changed(self: CaptureRetention, db, bid, ids, reason):
    row = db.execute(
        "UPDATE bot_streams SET captures_revision=captures_revision+1 WHERE bot_id=? RETURNING captures_revision",
        (bid,),
    ).fetchone()
    if row:
        self.store._event(
            db,
            bid,
            "captures.changed",
            {"revision": row[0], "removed_ids": ids, "reason": reason},
        )


def mark(self: CaptureRetention, db, rows):
    bots = {}
    for row, reason in rows:
        updated = db.execute(
            "UPDATE capture_storage SET state='pending_delete',reason=?,removed_at=? WHERE id=? AND state IN ('available','reserved')",
            (reason, stamp(), row["id"]),
        ).rowcount
        if updated:
            bots.setdefault(row["bot_id"], []).append(row["id"])
    for bid, ids in bots.items():
        self.changed(db, bid, ids, "retention")


def path(self: CaptureRetention, cid, temporary=False):
    if not re.fullmatch(r"capture_[a-f0-9]{32}", cid):
        raise OSError("Invalid capture storage identity")
    path = self.store.blobs / (cid + ".tmp" if temporary else cid)
    if path.is_symlink() or path.resolve().parent != self.store.blobs.resolve():
        raise OSError("Capture path is outside storage")
    return path


def delete_pending(self: CaptureRetention, wid=None):
    now = self.clock().timestamp()
    with self.store.transaction() as db:
        rows = db.execute(
            "SELECT * FROM capture_storage WHERE state='pending_delete' AND retry_at<=? AND (? IS NULL OR workspace_id=?) AND NOT EXISTS (SELECT 1 FROM workspaces w WHERE w.id=capture_storage.workspace_id AND w.deleted_at IS NOT NULL) ORDER BY sequence LIMIT ?",
            (now, wid, wid, BATCH),
        ).fetchall()
    for row in rows:
        try:
            self.path(row["id"]).unlink(missing_ok=True)
            self.path(row["id"], True).unlink(missing_ok=True)
        except OSError as exc:
            with self.store.transaction() as db:
                db.execute(
                    "UPDATE capture_storage SET attempts=attempts+1,retry_at=? WHERE id=?",
                    (now + min(300, 2 ** min(row["attempts"] + 1, 8)), row["id"]),
                )
                db.execute(
                    "UPDATE workspace_capture_retention SET last_error=?,cleanup_pending=1 WHERE workspace_id=?",
                    (
                        f"Screenshot deletion failed: {type(exc).__name__}",
                        row["workspace_id"],
                    ),
                )
            continue
        with self.store.transaction() as db:
            db.execute(
                "UPDATE capture_storage SET state='removed' WHERE id=?",
                (row["id"],),
            )
            db.execute("DELETE FROM capture_records WHERE id=?", (row["id"],))


def cleanup(self: CaptureRetention, wid, incoming=0):
    """One bounded pass, serialized with writers and image reads."""
    with self.store.lock:
        if is_deleted(self.store.database, wid):
            return False
        self.delete_pending(wid)
        with self.store.transaction() as db:
            p = self.policy(db, wid)
            selected = []
            target = p["target_bytes"]
            for row, reason, goal in self.candidates(db, wid, p, incoming):
                selected.append((row, reason))
                target = goal
                if len(selected) == BATCH:
                    break
            self.mark(db, selected)
            db.execute(
                "UPDATE workspace_capture_retention SET target_bytes=? WHERE workspace_id=?",
                (target, wid),
            )
        self.delete_pending(wid)
        with self.store.transaction() as db:
            p = self.policy(db, wid)
            more = next(self.candidates(db, wid, p, incoming), None) is not None
            pending = self.usage(db, wid)["pending_bytes"] > 0
            db.execute(
                "UPDATE workspace_capture_retention SET cleanup_pending=?,last_cleanup_at=?,last_error=CASE WHEN ? THEN last_error ELSE NULL END,target_bytes=CASE WHEN ? THEN target_bytes ELSE NULL END WHERE workspace_id=?",
                (
                    int(more or pending),
                    stamp(),
                    int(pending),
                    int(more or pending),
                    wid,
                ),
            )
            return not more and not pending


def sweep(self: CaptureRetention):
    with self.store.transaction() as db:
        workspaces = [
            r[0] for r in db.execute("SELECT workspace_id FROM workspace_capture_retention")
        ]
    for wid in workspaces:
        self.cleanup(wid)
    with self.store.lock:
        self.delete_pending()
        with self.store.transaction() as db:
            cutoff = (self.clock() - timedelta(days=self.store.retention_days)).isoformat()
            db.execute(
                "DELETE FROM capture_storage WHERE state='removed' AND removed_at<?",
                (cutoff,),
            )

    with self.store.transaction() as db:
        return bool(
            db.execute(
                "SELECT 1 FROM workspace_capture_retention WHERE cleanup_pending=1 LIMIT 1"
            ).fetchone()
        )


def recover(self: CaptureRetention):
    with self.store.lock:
        with self.store.transaction() as db:
            db.execute(
                "UPDATE capture_storage SET state='pending_delete',reason='interrupted_write',removed_at=? WHERE state='reserved'",
                (stamp(),),
            )
            db.execute("UPDATE capture_storage SET retry_at=0 WHERE state='pending_delete'")
            known = {r[0] for r in db.execute("SELECT id FROM capture_storage")}
        with self.store.transaction() as db:
            missing = []
            for row in db.execute("SELECT * FROM capture_storage WHERE state='available'"):
                try:
                    exists = self.path(row["id"]).is_file()
                except OSError:
                    exists = False
                if not exists:
                    missing.append((row, "missing"))
                    if len(missing) == BATCH:
                        self.mark(db, missing)
                        missing = []
            self.mark(db, missing)
        for path in self.store.blobs.iterdir():
            cid = path.name.removesuffix(".tmp")
            if re.fullmatch(r"capture_[a-f0-9]{32}", cid) and cid not in known:
                self.path(cid, path.name.endswith(".tmp")).unlink(missing_ok=True)
        self.sweep()


async def loop(self: CaptureRetention):
    backlogged = True
    while True:
        try:
            await asyncio.wait_for(self.wake.wait(), timeout=1 if backlogged else 60)
        except TimeoutError:
            pass
        self.wake.clear()
        worker = asyncio.create_task(asyncio.to_thread(self.sweep))
        try:
            backlogged = await asyncio.shield(worker)
            self.store.health.progressed("capture_cleanup")
        except asyncio.CancelledError:
            await worker  # Drain filesystem work before releasing the process lock.
            raise
