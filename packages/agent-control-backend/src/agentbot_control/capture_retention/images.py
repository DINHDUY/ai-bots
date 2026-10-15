from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from fastapi import HTTPException
from fastapi.responses import Response

from agentbot_control.capture_retention import BATCH, MAX_IMAGE
from agentbot_control.common import identifier, packed

if TYPE_CHECKING:
    from agentbot_control.capture_retention import CaptureRetention


def store_image(self: CaptureRetention, bid, rid, raw, metadata):
    cid = identifier("capture")
    with self.store.lock:
        with self.store.transaction() as db:
            wid = db.execute(
                "SELECT workspace_id FROM bot_streams WHERE bot_id=?", (bid,)
            ).fetchone()[0]
        ready = self.cleanup(wid, len(raw))
        with self.store.transaction() as db:
            p = self.policy(db, wid)
            u = self.usage(db, wid)
            remaining = next(self.candidates(db, wid, p, len(raw)), None)
            if (
                not ready
                or remaining
                or u["shared_bytes"] + len(raw) > self.store.blob_limit
                or (p["max_bytes"] and u["screenshot_bytes"] + len(raw) > p["max_bytes"])
            ):
                return self.skipped(
                    db,
                    bid,
                    rid,
                    "Screenshot storage is full or cleanup is pending.",
                )
            db.execute(
                "INSERT INTO capture_storage(id,bot_id,workspace_id,size,created_at,state) VALUES (?,?,?,?,?,'reserved')",
                (cid, bid, wid, len(raw), self.clock().isoformat()),
            )
        try:
            temporary = self.path(cid, True)
            temporary.write_bytes(raw)
            temporary.replace(self.path(cid))
            with self.store.transaction() as db:
                from agentbot_control.shared_computers.resolution import computer_for

                computer = computer_for(db, bid)
                created = self.clock().isoformat()
                db.execute(
                    "INSERT INTO capture_records(id,bot_id,size,created_at,session_id,metadata) VALUES (?,?,?,?,?,?)",
                    (
                        cid,
                        bid,
                        len(raw),
                        created,
                        computer["id"] if computer else None,
                        packed(metadata),
                    ),
                )
                rev = db.execute(
                    "UPDATE bot_streams SET captures_revision=captures_revision+1 WHERE bot_id=? RETURNING captures_revision",
                    (bid,),
                ).fetchone()[0]
                sequence = db.execute(
                    "SELECT sequence FROM capture_storage WHERE id=?", (cid,)
                ).fetchone()[0]
                data = {
                    "storage_sequence": sequence,
                    "capture_id": cid,
                    "url": f"/api/bots/{bid}/captures/{cid}",
                    "capture": metadata,
                    "created_at": created,
                    "expires_at": self.expiry(created, p),
                    "revision": rev,
                    "retained": True,
                }
                self.store._event(
                    db,
                    bid,
                    "capture.available",
                    data,
                    rid,
                    metadata.get("action_id"),
                )
                return data
        except (OSError, sqlite3.Error) as exc:
            # Includes database commit failures: the reserved ledger survives.
            with self.store.transaction() as db:
                row = db.execute("SELECT * FROM capture_storage WHERE id=?", (cid,)).fetchone()
                if row:
                    self.mark(db, [(row, "write_failed")])
                return self.skipped(
                    db,
                    bid,
                    rid,
                    f"Screenshot could not be stored: {type(exc).__name__}.",
                )


def skipped(self: CaptureRetention, db, bid, rid, reason):
    result = {"retained": False, "reason": reason}
    self.store._event(db, bid, "capture.skipped", result, rid)
    return result


def expiry(self: CaptureRetention, created, p):
    return (
        (datetime.fromisoformat(created) + timedelta(seconds=p["max_age_seconds"])).isoformat()
        if p["max_age_seconds"]
        else None
    )


def history_db(
    self: CaptureRetention,
    db,
    bid,
    surface=None,
    before=None,
    limit=100,
    before_sequence=None,
    session_id=None,
):
    workspace = db.execute("SELECT workspace_id FROM bot_streams WHERE bot_id=?", (bid,)).fetchone()
    if not workspace:
        return []
    p = self.policy(db, workspace[0])
    cutoff = (
        (self.clock() - timedelta(seconds=p["max_age_seconds"])).isoformat()
        if p["max_age_seconds"]
        else ""
    )
    rows = db.execute(
        "SELECT c.*,s.sequence,b.workspace_id FROM capture_records c JOIN capture_storage s ON s.id=c.id JOIN bot_streams b ON b.bot_id=c.bot_id WHERE c.bot_id=? AND s.state='available' AND c.created_at>? AND c.created_at<? AND (? IS NULL OR s.sequence<?) AND (? IS NULL OR json_extract(c.metadata,'$.surface_kind')=?) AND (? IS NULL OR c.session_id=?) ORDER BY s.sequence DESC",
        (
            bid,
            cutoff,
            before or "9999",
            before_sequence,
            before_sequence,
            surface,
            surface,
            session_id,
            session_id,
        ),
    )
    result, missing = [], []
    for row in rows:
        expiry = self.expiry(row["created_at"], p)
        if expiry and expiry <= self.clock().isoformat():
            continue
        try:
            exists = self.path(row["id"]).is_file()
        except OSError:
            exists = False
        if not exists:
            missing.append((row, "missing"))
            if len(missing) == BATCH:
                self.mark(db, missing)
                missing = []
            continue
        result.append(
            {
                "capture_id": row["id"],
                "url": f"/api/bots/{bid}/captures/{row['id']}",
                "capture": json.loads(row["metadata"] or "{}"),
                "created_at": row["created_at"],
                "session_id": row["session_id"],
                "storage_sequence": row["sequence"],
                "expires_at": expiry,
            }
        )
        if len(result) >= limit:
            break
    self.mark(db, missing)
    return result


def read(self: CaptureRetention, bid, cid):
    with self.store.lock:
        with self.store.transaction() as db:
            row = db.execute(
                "SELECT c.*,s.workspace_id FROM capture_records c JOIN capture_storage s ON s.id=c.id WHERE c.id=? AND c.bot_id=? AND s.state='available'",
                (cid, bid),
            ).fetchone()
            if not row:
                return None
            expiry = self.expiry(row["created_at"], self.policy(db, row["workspace_id"]))
            if expiry and expiry <= self.clock().isoformat():
                return None
        try:
            with self.path(cid).open("rb") as stream:
                raw = stream.read(MAX_IMAGE + 1)
            if len(raw) > MAX_IMAGE:
                raise OSError("Capture exceeds stored image limit")
            return raw
        except OSError:
            with self.store.transaction() as db:
                self.mark(db, [(row, "missing")])
            return None


def response(self: CaptureRetention, bid, cid):
    raw = self.read(bid, cid)
    if raw is None:
        raise HTTPException(404, "Capture unavailable or expired.")
    return Response(
        raw,
        media_type="image/png",
        headers={
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )
