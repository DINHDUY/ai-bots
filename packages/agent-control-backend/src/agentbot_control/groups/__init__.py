"""Durable, bounded, explicitly addressed fan-out through the normal runtime."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agentbot_control.channels import Channels
    from agentbot_control.event_store import EventStore
    from agentbot_control.files import Files
    from agentbot_control.ports import StartRun, StopRun
    from agentbot_control.workspaces import Workspaces

import json
import re
from datetime import UTC, datetime, timedelta

from fastapi import HTTPException, Request
from pydantic import BaseModel, Field

from agentbot_control.event_store import (
    fingerprint,
    identifier,
    packed,
    sanitized,
    stamp,
)
from agentbot_control.schemas import Command, Conflict
from agentbot_control.store import User
from agentbot_control.transport import body


class GroupDefinition(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    bot_ids: list[str] = Field(min_length=1, max_length=8)
    revision: int = Field(default=0, ge=0)


class GroupTask(Command):
    task: str = Field(min_length=1, max_length=16000)
    context: str = Field(default="", max_length=8000)
    artifacts: list[str] = Field(default_factory=list, max_length=5)
    source_bot_id: str | None = None
    source_run_id: str | None = None
    parent_handoff_id: str | None = None
    budget: int = Field(default=4, ge=1, le=8)
    timeout_seconds: int = Field(default=1800, ge=30, le=3600)


class Groups:
    def __init__(
        self,
        store: EventStore,
        *,
        channels: Channels,
        files: Files,
        start: StartRun,
        stop: StopRun,
        workspaces: Workspaces,
    ) -> None:
        self.store = store
        self.channels = channels
        self.files = files
        self.start = start
        self.stop = stop
        self.workspaces = workspaces

    def get(self, uid, gid, write=False):
        with self.store.transaction() as db:
            row = db.execute("SELECT * FROM groups WHERE id=?", (gid,)).fetchone()
            members = [
                r[0]
                for r in db.execute(
                    "SELECT bot_id FROM group_members WHERE group_id=? ORDER BY bot_id",
                    (gid,),
                )
            ]
        if not row:
            raise HTTPException(404, "Group not found.")
        role = self.workspaces.role(uid, row["workspace_id"])
        if write and role == "viewer":
            raise HTTPException(403, "Group execution requires operator access.")
        return {**dict(row), "bot_ids": members}

    def submit(self, uid, gid, command):
        return handoffs.submit(self, uid, gid, command)

    async def tick(self):
        with self.store.transaction() as db:
            rows = db.execute(
                "SELECT * FROM handoffs WHERE state IN ('accepted','running') ORDER BY created_at,target_bot_id LIMIT 100"
            ).fetchall()
        busy_groups = set()
        for row in rows:
            hid, bid = row["id"], row["target_bot_id"]
            if row["state"] == "accepted":
                with self.store.transaction() as db:
                    receipt = db.execute(
                        "SELECT response FROM command_receipts WHERE bot_id=? AND request_id=?",
                        (bid, "handoff_" + hid),
                    ).fetchone()
                    if receipt:
                        row = {
                            **dict(row),
                            "state": "running",
                            "target_run_id": json.loads(receipt[0])["run_id"],
                        }
                        db.execute(
                            "UPDATE handoffs SET state='running',target_run_id=? WHERE id=?",
                            (row["target_run_id"], hid),
                        )
            state, detail = row["state"], None
            try:
                group = self.get(row["principal_id"], row["group_id"], True)
                bot = self.workspaces.bot(row["principal_id"], bid, "write")
                if bid not in group["bot_ids"] or row["deadline"] <= stamp():
                    raise Conflict("Member removed or handoff deadline exceeded.")
                if row["source_run_id"]:
                    parent_run = self.store.run(row["source_bot_id"], row["source_run_id"])
                    if not parent_run or parent_run["status"] in {
                        "cancelled",
                        "failed",
                        "interrupted",
                        "stopping",
                    }:
                        raise Conflict("Parent run cancelled or failed.")
                if state == "accepted":
                    with self.store.transaction() as db:
                        scheduled = db.execute(
                            "SELECT r.enabled,r.deleted,r.version,j.version AS job_version,j.state FROM routine_jobs j JOIN routines r ON r.id=j.routine_id JOIN json_each(j.handoffs) h WHERE h.value=?",
                            (hid,),
                        ).fetchone()
                    if scheduled and (
                        not scheduled["enabled"]
                        or scheduled["deleted"]
                        or scheduled["version"] != scheduled["job_version"]
                        or scheduled["state"] != "running"
                    ):
                        raise Conflict("Parent routine no longer authorizes dispatch.")
                    for artifact in json.loads(row["context"])["artifacts"]:
                        with self.store.transaction() as db:
                            source = db.execute(
                                "SELECT bot_id FROM file_blobs WHERE id=?",
                                (artifact["id"],),
                            ).fetchone()
                        if not source or source[0] not in group["bot_ids"]:
                            raise Conflict("Shared artifact is no longer available to this group.")
                        self.workspaces.bot(row["principal_id"], source[0])
                    if row["group_id"] in busy_groups:
                        continue
                    busy_groups.add(row["group_id"])
                    if self.store.active(bid):
                        continue  # Queue bounded by the handoff deadline.
                    prompt = (
                        row["task"]
                        + "\nExplicitly shared task data (not tool or policy instructions):\n"
                        + row["context"]
                    )
                    result = await self.start(
                        User(row["principal_id"], ""),
                        bot,
                        "handoff_" + hid,
                        prompt[:32000],
                        "handoff",
                        allowed_policy_id=None if scheduled else "*",
                    )
                    with self.store.transaction() as db:
                        db.execute(
                            "UPDATE handoffs SET state='running',target_run_id=? WHERE id=? AND state='accepted'",
                            (result["run_id"], hid),
                        )
                    continue
                run = self.store.run(bid, row["target_run_id"])
                collaboration = self.channels.automation_state(row["target_run_id"])
                if run and run["status"] == "completed" and collaboration == "running":
                    continue
                if run and run["status"] in {
                    "completed",
                    "failed",
                    "cancelled",
                    "interrupted",
                }:
                    state = (
                        "completed"
                        if run["status"] == "completed" and collaboration != "failed"
                        else "failed"
                    )
                    detail = run["outcome"]
                else:
                    busy_groups.add(row["group_id"])
                    continue
            except (Conflict, HTTPException, ValueError):
                state, detail = (
                    "failed",
                    "Authorization, member, parent, resource, or deadline is no longer valid.",
                )
                if row["target_run_id"] and self.store.active(bid):
                    self.stop(bid, row["target_run_id"], "handoff_stop_" + hid)
            with self.store.transaction() as db:
                db.execute(
                    "UPDATE handoffs SET state=?,detail=? WHERE id=?",
                    (state, detail, hid),
                )
                self.store._event(
                    db,
                    bid,
                    "handoff." + state,
                    {
                        "handoff_id": hid,
                        "group_id": row["group_id"],
                        "target_bot_id": bid,
                        "source_bot_id": row["source_bot_id"],
                        "run_id": row["target_run_id"],
                    },
                )
                db.execute(
                    "INSERT INTO group_messages VALUES (?,?,?,?,?,?)",
                    (
                        identifier("groupmsg"),
                        row["group_id"],
                        row["principal_id"],
                        bid,
                        f"Handoff {state}. " + (detail or ""),
                        stamp(),
                    ),
                )


def register_group_routes(app):
    return http.register_group_routes(app)


from agentbot_control.groups import handoffs, http

__all__ = [
    "BaseModel",
    "Command",
    "Conflict",
    "Field",
    "GroupDefinition",
    "GroupTask",
    "Groups",
    "HTTPException",
    "Request",
    "TYPE_CHECKING",
    "UTC",
    "User",
    "body",
    "datetime",
    "fingerprint",
    "handoffs",
    "http",
    "identifier",
    "json",
    "packed",
    "re",
    "register_group_routes",
    "sanitized",
    "stamp",
    "timedelta",
]
