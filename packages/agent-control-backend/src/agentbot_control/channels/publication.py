from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from agentbot_control.channels import bounded
from agentbot_control.event_store import (
    fingerprint,
    identifier,
    packed,
    protected,
    stamp,
)
from agentbot_control.schemas import Conflict

if TYPE_CHECKING:
    from agentbot_control.channels import Channels


def _post(
    self: Channels,
    db,
    wid,
    uid,
    kind,
    text,
    key,
    *,
    tid=None,
    source=None,
    rid=None,
    recipient=None,
    reply_to=None,
    mode="communication",
    depth=0,
    artifact_ids=(),
):
    text = bounded(text)
    self._role(db, uid, wid, write=True)
    if (
        not isinstance(artifact_ids, (list, tuple))
        or len(artifact_ids) > 5
        or any(not isinstance(aid, str) for aid in artifact_ids)
    ):
        raise Conflict("Select at most five retained text artifacts.")
    artifacts = [self._artifact(db, wid, uid, aid) for aid in dict.fromkeys(artifact_ids)]
    if len(text.encode()) + len(packed(artifacts).encode()) > 16384:
        raise Conflict("Message and shared artifact context exceed 16 KiB.")
    digest = fingerprint(
        {
            "kind": kind,
            "text": text,
            "tid": tid,
            "recipient": recipient,
            "reply_to": reply_to,
            "mode": mode,
            "artifacts": artifacts,
        }
    )
    previous = db.execute(
        "SELECT * FROM channel_messages WHERE workspace_id=? AND request_key=?",
        (wid, key),
    ).fetchone()
    if previous:
        if previous["digest"] != digest:
            raise Conflict("Request ID reused with a different message.")
        return dict(previous)
    self._role(db, uid, wid, write=True)
    if not self._channel(db, wid)["enabled"]:
        raise Conflict("collaboration_disabled")
    if not tid:
        tid = self._new_thread(db, wid, uid, recipient if kind == "request" else None)
    thread = self._thread(db, tid, wid, uid)
    if thread["messages_used"] >= 32:
        raise Conflict("budget_exhausted")
    cutoff = (datetime.now(UTC) - timedelta(minutes=1)).isoformat()
    count = db.execute(
        "SELECT COUNT(*),SUM(sender_bot_id=?) FROM channel_messages WHERE workspace_id=? AND created_at>? AND kind!='system'",
        (source["bot_id"] if source else None, wid, cutoff),
    ).fetchone()
    if count[0] >= 100 or (count[1] or 0) >= 10:
        raise Conflict("Channel message rate limit reached.")
    target = None
    if kind == "request":
        self._authorize(db, uid, recipient, wid)
        target = self._participant(db, recipient, wid)
        if source and source["bot_id"] == recipient:
            raise Conflict("Self messaging is not supported.")
        if depth > 3 or thread["runs_used"] >= thread["run_limit"]:
            raise Conflict("budget_exhausted")
        # Only pending ancestors count as cycles; replies do not create delegation edges.
        ancestor = rid
        for _ in range(5):
            ctx = db.execute(
                "SELECT request_message_id FROM channel_run_context WHERE run_id=?",
                (ancestor,),
            ).fetchone()
            parent = (
                db.execute(
                    "SELECT sender_bot_id,sender_run_id FROM channel_messages WHERE id=?",
                    (ctx[0],),
                ).fetchone()
                if ctx and ctx[0]
                else None
            )
            if not parent:
                break
            if parent["sender_bot_id"] == recipient:
                raise Conflict("Delegation cycle rejected.")
            ancestor = parent["sender_run_id"]
        queues = db.execute(
            "SELECT COUNT(*),SUM(d.target_bot_id=?) FROM channel_deliveries d JOIN channel_threads t ON t.id=d.thread_id WHERE t.workspace_id=? AND d.state IN ('queued','blocked')",
            (recipient, wid),
        ).fetchone()
        if queues[0] >= 128 or (queues[1] or 0) >= 16:
            raise Conflict("queue_full")
    if kind == "reply":
        request = db.execute(
            "SELECT * FROM channel_messages WHERE id=? AND thread_id=? AND kind='request'",
            (reply_to, tid),
        ).fetchone()
        if (
            not request
            or not source
            or request["recipient_id"] != source["bot_id"]
            or request["recipient_enrollment"] != source["enrollment_id"]
        ):
            raise Conflict("Reply does not belong to this bot's enrollment.")
        ctx = db.execute(
            "SELECT request_message_id FROM channel_run_context WHERE run_id=?",
            (rid,),
        ).fetchone()
        if not ctx or ctx[0] != reply_to:
            raise Conflict("Reply must answer this run's assigned request.")
        existing = db.execute(
            "SELECT * FROM channel_messages WHERE reply_to=? AND kind='reply'",
            (reply_to,),
        ).fetchone()
        if existing:
            if existing["body"] == text:
                return dict(existing)
            raise Conflict("This request already has a reply.")
        recipient = request["sender_bot_id"]
    mid = identifier("channelmsg")
    seq = self.event(
        db,
        wid,
        "message.posted",
        {"message_id": mid, "thread_id": tid, "kind": kind},
    )
    db.execute(
        "INSERT INTO channel_messages VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            mid,
            wid,
            tid,
            seq,
            source["bot_id"] if source else None,
            source["name"] if source else "Workspace member",
            rid,
            uid,
            kind,
            recipient,
            target["enrollment_id"] if target else None,
            reply_to,
            text,
            key,
            digest,
            stamp(),
        ),
    )
    db.execute(
        "UPDATE channel_threads SET messages_used=messages_used+1 WHERE id=?",
        (tid,),
    )
    for artifact in artifacts:
        db.execute(
            "INSERT INTO channel_artifact_grants VALUES (?,?,?,?,?,?,0)",
            (
                identifier("channelartifact"),
                mid,
                wid,
                artifact["id"],
                artifact["revision"],
                uid,
            ),
        )
    if target:
        db.execute(
            "INSERT INTO channel_deliveries(id,thread_id,message_id,target_bot_id,target_enrollment,source_bot_id,source_enrollment,source_run_id,mode,depth,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (
                identifier("delivery"),
                tid,
                mid,
                recipient,
                target["enrollment_id"],
                source["bot_id"] if source else None,
                source["enrollment_id"] if source else None,
                rid,
                mode,
                depth,
                stamp(),
            ),
        )
    return dict(db.execute("SELECT * FROM channel_messages WHERE id=?", (mid,)).fetchone())


def post(self: Channels, uid, wid, command):
    self.available()
    with self.store.transaction() as db:
        self.expire(db)
        return self._post(
            db,
            wid,
            uid,
            command.kind,
            command.text,
            uid + ":" + command.request_id,
            tid=command.thread_id,
            recipient=command.recipient_id,
            mode="computer" if command.requires_computer else "communication",
            artifact_ids=command.artifact_ids,
        )


def _artifact(self: Channels, db, wid, uid, aid):
    self._role(db, uid, wid)
    row = db.execute(
        "SELECT f.* FROM file_blobs f JOIN bots b ON b.id=f.bot_id JOIN bot_streams s ON s.bot_id=b.id WHERE f.id=? AND b.owner_id=? AND s.workspace_id=? AND b.framework NOT IN ('ufo','open_interface')",
        (aid, uid, wid),
    ).fetchone()
    if (
        not row
        or protected(row["path"])
        or row["size"] > 16384
        or not aid.startswith("blob_")
        or any(c not in "abcdefghijklmnopqrstuvwxyz0123456789_" for c in aid)
    ):
        raise Conflict("Artifact is unavailable for publication to this workspace.")
    path = self.files.blobs.directory / aid
    try:
        raw = path.read_bytes()
        if len(raw) != row["size"] or hashlib.sha256(raw).hexdigest() != row["revision"]:
            raise Conflict("Retained artifact changed.")
        content = raw.decode("utf-8")
    except (OSError, UnicodeError) as exc:
        raise Conflict("Retained text artifact unavailable.") from exc
    return {
        "id": aid,
        "revision": row["revision"],
        "path": row["path"],
        "content": content,
    }


def _artifact_context(self: Channels, db, wid, mid):
    result = []
    for grant in db.execute("SELECT * FROM channel_artifact_grants WHERE message_id=?", (mid,)):
        if grant["revoked"]:
            raise Conflict("Shared artifact grant revoked.")
        artifact = self._artifact(db, wid, grant["published_by"], grant["blob_id"])
        if artifact["revision"] != grant["revision"]:
            raise Conflict("Shared artifact revision changed.")
        result.append(artifact)
    return result
