from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import HTTPException

from agentbot_control.channels import LIBRARY, TOOL
from agentbot_control.event_store import (
    packed,
    stamp,
)
from agentbot_control.schemas import Conflict

if TYPE_CHECKING:
    from agentbot_control.channels import Channels


def _channel(self: Channels, db, wid):
    db.execute("INSERT OR IGNORE INTO workspace_channels(workspace_id) VALUES (?)", (wid,))
    return db.execute("SELECT * FROM workspace_channels WHERE workspace_id=?", (wid,)).fetchone()


def _role(self: Channels, db, uid, wid, *, write=False, owner=False):
    row = db.execute(
        "SELECT role FROM workspace_members WHERE workspace_id=? AND user_id=?",
        (wid, uid),
    ).fetchone()
    if not row or (owner and row[0] != "owner"):
        raise HTTPException(404, "Workspace unavailable.")
    if write and row[0] == "viewer":
        raise HTTPException(403, "Operator access required.")
    return row[0]


def _authorize(self: Channels, db, uid, bid, wid):
    self._role(db, uid, wid, write=True)
    bot = db.execute(
        "SELECT b.* FROM bots b JOIN bot_streams s ON s.bot_id=b.id WHERE b.id=? AND s.workspace_id=?",
        (bid, wid),
    ).fetchone()
    if not bot:
        raise Conflict("recipient_removed")
    if bot["owner_id"] != uid:
        cloud = db.execute(
            "SELECT provider FROM cloud_compute_config WHERE bot_id=?", (bid,)
        ).fetchone()
        if bot["framework"] in {"ufo", "open_interface"} or (
            cloud and cloud[0] == "azure_ml_compute_instance"
        ):
            raise Conflict("execution_access_required")
        role = self._role(db, uid, wid)
        grant = db.execute(
            "SELECT 1 FROM execution_grants WHERE bot_id=? AND user_id=?",
            (bid, uid),
        ).fetchone()
        if role != "operator" or not grant:
            raise Conflict("execution_access_required")
    return bot


def event(self: Channels, db, wid, kind, data, *, directory=False):
    self._channel(db, wid)
    db.execute(
        "UPDATE workspace_channels SET seq=seq+1,directory_revision=directory_revision+? WHERE workspace_id=?",
        (int(directory), wid),
    )
    seq = db.execute("SELECT seq FROM workspace_channels WHERE workspace_id=?", (wid,)).fetchone()[
        0
    ]
    db.execute(
        "INSERT INTO workspace_channel_events VALUES (?,?,?,?,?)",
        (wid, seq, kind, packed(data), stamp()),
    )
    return seq


def _has_bundle(self: Channels, db, bid):
    return db.execute(
        "SELECT 1 FROM bot_tool_bindings WHERE bot_id=? AND library_id=? AND tool_id=? AND enabled=1",
        (bid, LIBRARY, TOOL),
    ).fetchone()


def _participant(self: Channels, db, bid, wid, generation=None):
    row = db.execute(
        "SELECT * FROM workspace_bot_directory WHERE bot_id=? AND workspace_id=?",
        (bid, wid),
    ).fetchone()
    if not row or row["state"] != "enabled" or not row["published"]:
        raise Conflict(
            "recipient_removed"
            if not row or row["state"] in {"removed", "leaving"}
            else "participation_" + row["state"]
        )
    if row["expires_at"] and row["expires_at"] <= stamp():
        raise Conflict("participation_expired")
    if generation and generation != row["enrollment_id"]:
        raise Conflict("recipient_enrollment_changed")
    if not self._has_bundle(db, bid):
        raise Conflict("messaging_tool_removed")
    if not self._channel(db, wid)["enabled"]:
        raise Conflict("collaboration_disabled")
    return row
