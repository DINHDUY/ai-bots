from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from agentbot_control.event_store import (
    fingerprint,
    identifier,
    packed,
    sanitized,
    stamp,
)
from agentbot_control.schemas import Conflict

if TYPE_CHECKING:
    from agentbot_control.groups import Groups


def submit(self: Groups, uid, gid, command):
    group = self.get(uid, gid, True)
    # Names are presentation only: explicit @bot IDs and @group are stable and unambiguous.
    mentioned = re.findall(r"@([A-Za-z0-9_-]+)", command.task)
    targets = (
        group["bot_ids"] if "group" in mentioned else sorted(set(mentioned) & set(group["bot_ids"]))
    )
    if not targets or len(targets) > command.budget:
        raise Conflict("Mention @group or a member @bot_id within the execution budget.")
    for bid in targets:
        self.workspaces.bot(uid, bid, "write")
    context = {
        "approved_text": command.context,
        "artifacts": [],
        "request_digest": fingerprint(command.model_dump()),
    }
    for aid in command.artifacts:
        with self.store.transaction() as db:
            artifact = db.execute("SELECT bot_id FROM file_blobs WHERE id=?", (aid,)).fetchone()
        if not artifact or artifact[0] not in group["bot_ids"]:
            raise Conflict("Artifact is not a retained version from a group member.")
        self.workspaces.bot(uid, artifact[0])
        blob = self.files.blobs.get(artifact[0], aid)
        if not blob:
            raise Conflict("Retained artifact is unavailable.")
        meta, path = blob
        if meta["size"] > 65536:
            raise Conflict("Shared text artifacts must fit the 64 KiB context limit.")
        try:
            content = path.read_bytes().decode("utf-8")
        except UnicodeError:
            raise Conflict("Binary artifacts cannot be included as text context.")
        context["artifacts"].append(
            {
                "id": aid,
                "revision": meta["revision"],
                "path": meta["path"],
                "content": content,
            }
        )
    correlation, hop = identifier("correlation"), 0
    deadline = (datetime.now(UTC) + timedelta(seconds=command.timeout_seconds)).isoformat()
    if command.source_bot_id:
        if command.source_bot_id not in group["bot_ids"] or not self.store.run(
            command.source_bot_id, command.source_run_id
        ):
            raise Conflict("Source bot/run is not a group member run.")
    if command.parent_handoff_id:
        with self.store.transaction() as db:
            parent = db.execute(
                "SELECT * FROM handoffs WHERE id=? AND group_id=? AND principal_id=?",
                (command.parent_handoff_id, gid, uid),
            ).fetchone()
            used = (
                db.execute(
                    "SELECT COUNT(*) FROM handoffs WHERE correlation_id=?",
                    (parent["correlation_id"],),
                ).fetchone()[0]
                if parent
                else 0
            )
        if (
            not parent
            or parent["state"] not in {"running", "completed"}
            or parent["target_bot_id"] != command.source_bot_id
            or parent["target_run_id"] != command.source_run_id
        ):
            raise Conflict("Invalid parent handoff.")
        correlation, hop, deadline = (
            parent["correlation_id"],
            parent["hop"] + 1,
            min(deadline, parent["deadline"]),
        )
        if hop > 3 or used + len(targets) > parent["budget"]:
            raise Conflict("Handoff hop or execution budget exhausted.")
    with self.store.transaction() as db:
        previous = db.execute(
            "SELECT * FROM handoffs WHERE group_id=? AND request_id=? ORDER BY target_bot_id",
            (gid, command.request_id),
        ).fetchall()
        if previous:
            if [r["target_bot_id"] for r in previous] != targets or any(
                r["task"] != command.task or r["context"] != packed(context) for r in previous
            ):
                raise Conflict("Request ID reused with different group task.")
            return [dict(r) for r in previous]
        if db.execute(
            "SELECT 1 FROM handoffs WHERE correlation_id=? AND target_bot_id IN ("
            + ",".join("?" for _ in targets)
            + ")",
            (correlation, *targets),
        ).fetchone():
            raise Conflict("Handoff cycle rejected.")
        ids = []
        for bid in targets:
            hid = identifier("handoff")
            db.execute(
                "INSERT INTO handoffs VALUES (?,?,?,?,?,?,?,NULL,?,?,?,?,?,?,'accepted',?,NULL)",
                (
                    hid,
                    gid,
                    command.request_id,
                    uid,
                    command.source_bot_id,
                    command.source_run_id,
                    bid,
                    sanitized(command.task),
                    packed(context),
                    correlation,
                    hop,
                    command.budget,
                    deadline,
                    stamp(),
                ),
            )
            self.store._event(
                db,
                bid,
                "handoff.accepted",
                {
                    "handoff_id": hid,
                    "source_bot_id": command.source_bot_id,
                    "target_bot_id": bid,
                    "group_id": gid,
                    "correlation_id": correlation,
                },
            )
            ids.append(hid)
        db.execute(
            "INSERT INTO group_messages VALUES (?,?,?,NULL,?,?)",
            (identifier("groupmsg"), gid, uid, sanitized(command.task), stamp()),
        )
    return [{"id": hid, "state": "accepted"} for hid in ids]
