"""Atomic workspace deletion command within the caller's transaction."""

from fastapi import HTTPException

from agentbot_control.common import packed, stamp
from agentbot_control.repositories import workspace_deletions as rows
from agentbot_control.repositories.workspace_preview import preview
from agentbot_control.repositories.workspace_purge import purge
from agentbot_control.schemas import Conflict


def commit(db, owner, wid, command, digest, enabled, changed):
    previous = rows.receipt(db, owner, command.request_id)
    if previous:
        if previous["fingerprint"] != digest:
            raise Conflict("This request ID was already used for a different deletion.")
        return rows.result(db, previous)
    if not enabled():
        raise HTTPException(409, "Workspace deletion is unavailable.")
    checked = preview(db, owner, wid)
    if command.confirm_name != checked.workspace_name:
        raise HTTPException(422, "Enter the exact workspace name.")
    if checked.blockers:
        raise HTTPException(
            409,
            {
                "code": checked.blockers[0].code,
                "blockers": [b.model_dump() for b in checked.blockers],
            },
        )
    if command.preview_digest != checked.preview_digest:
        raise Conflict("Workspace contents changed. Preview deletion again.", code="preview_stale")
    now = stamp()
    bot_ids = purge(db, wid, now)
    db.execute(
        "INSERT INTO workspace_deletions VALUES (?,?,?,?,?,?,?,?)",
        (
            owner,
            command.request_id,
            wid,
            digest,
            checked.workspace_name,
            packed(checked.counts),
            packed([r.model_dump() for r in checked.retained]),
            now,
        ),
    )
    for bid in bot_ids:
        changed(bid)
    saved = rows.receipt(db, owner, command.request_id)
    assert saved is not None
    return rows.result(db, saved)
