from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from fastapi import HTTPException

from agentbot_control.channels import OPEN
from agentbot_control.event_store import (
    identifier,
    packed,
    stamp,
)
from agentbot_control.schemas import ACTIVE_RUNS, Conflict

if TYPE_CHECKING:
    from agentbot_control.channels import Channels


def _directory(self: Channels, db, wid, query="", offset=0):
    if (
        type(offset) is not int
        or not 0 <= offset <= 100000
        or not isinstance(query, str)
        or len(query) > 400
    ):
        raise Conflict("Invalid directory query.")
    rows = db.execute(
        "SELECT * FROM workspace_bot_directory WHERE workspace_id=? AND published=1 AND (instr(lower(name),lower(?))>0 OR instr(lower(purpose),lower(?))>0 OR instr(lower(capabilities),lower(?))>0) ORDER BY CASE state WHEN 'enabled' THEN 0 ELSE 1 END,name,bot_id LIMIT 21 OFFSET ?",
        (wid, query, query, query, offset),
    ).fetchall()
    result, size = [], 0
    for row in rows[:20]:
        entry = {
            k: row[k]
            for k in (
                "bot_id",
                "name",
                "purpose",
                "state",
                "enrollment_id",
                "revision",
                "expires_at",
            )
        }
        entry["capabilities"] = json.loads(row["capabilities"])
        active = self.store._active(db, row["bot_id"])
        entry["availability"] = "busy" if active else "ready"
        computer = db.execute(
            "SELECT c.status,co.paused FROM computer_sessions c LEFT JOIN computer_control co ON co.session_id=c.id WHERE c.bot_id=? ORDER BY generation DESC LIMIT 1",
            (row["bot_id"],),
        ).fetchone()
        entry["computer"] = (
            "paused"
            if computer and computer["paused"]
            else computer["status"]
            if computer
            else "offline"
        )
        if row["state"] != "enabled":
            entry["availability"] = row["state"]
        size += len(packed(entry).encode())
        if size > 8192 and result:
            break
        result.append(entry)
    return {
        "bots": result,
        "revision": self._channel(db, wid)["directory_revision"],
        "next_offset": offset + len(result) if len(rows) > len(result) else None,
    }


def directory(self: Channels, uid, wid, query="", offset=0):
    self.available()
    with self.store.transaction() as db:
        self._role(db, uid, wid)
        self.expire(db)
        return self._directory(db, wid, query, offset)


def _messages(self: Channels, db, wid, thread_id=None, before=0):
    rows = db.execute(
        "SELECT * FROM channel_messages WHERE workspace_id=? AND (? IS NULL OR thread_id=?) AND (?=0 OR seq<?) ORDER BY seq DESC LIMIT 51",
        (wid, thread_id, thread_id, before, before),
    ).fetchall()
    selected, size = [], 0
    for row in rows[:50]:
        value = dict(row)
        value["artifacts"] = [
            dict(a)
            for a in db.execute(
                "SELECT id,blob_id,revision,revoked FROM channel_artifact_grants WHERE message_id=?",
                (row["id"],),
            )
        ]
        size += len(packed(value).encode())
        if size > 16384 and selected:
            break
        selected.append(value)
    return {
        "messages": list(reversed(selected)),
        "next_before": selected[-1]["seq"] if len(rows) > len(selected) else None,
    }


def snapshot(self: Channels, uid, wid):
    self.available()
    with self.store.transaction() as db:
        role = self._role(db, uid, wid)
        self.expire(db)
        channel = dict(self._channel(db, wid))
        policy = db.execute(
            "SELECT enabled FROM channel_enrollment_policies WHERE workspace_id=? AND owner_id=?",
            (wid, uid),
        ).fetchone()
        owned = [
            dict(r)
            for r in db.execute(
                "SELECT bot_id,name,purpose,state,published,revision,expires_at FROM workspace_bot_directory WHERE workspace_id=? AND owner_id=? AND state!='removed'",
                (wid, uid),
            )
        ]
        threads = [
            dict(r)
            for r in db.execute(
                "SELECT * FROM channel_threads WHERE workspace_id=? AND messages_used>0 ORDER BY created_at DESC LIMIT 100",
                (wid,),
            )
        ]
        deliveries = [
            dict(r)
            for r in db.execute(
                "SELECT d.* FROM channel_deliveries d JOIN channel_threads t ON t.id=d.thread_id WHERE t.workspace_id=? ORDER BY d.created_at DESC LIMIT 200",
                (wid,),
            )
        ]
        # Private bot/run history remains private even if its profile was published.
        for delivery in deliveries:
            try:
                self._authorize(db, uid, delivery["target_bot_id"], wid)
            except (HTTPException, Conflict):
                delivery["run_id"] = None
        return {
            **channel,
            "role": role,
            "enroll_future": bool(policy and policy[0]),
            "owned_bots": owned,
            "directory": self._directory(db, wid),
            **self._messages(db, wid),
            "threads": threads,
            "deliveries": deliveries,
        }


def _new_thread(self: Channels, db, wid, uid, bid=None, rid=None):
    tid = identifier("thread")
    deadline = (datetime.now(UTC) + timedelta(minutes=30)).isoformat()
    db.execute(
        "INSERT INTO channel_threads(id,workspace_id,principal_id,origin_bot_id,origin_run_id,deadline,created_at) VALUES (?,?,?,?,?,?,?)",
        (tid, wid, uid, bid, rid, deadline, stamp()),
    )
    if rid:
        config = db.execute("SELECT config FROM runs WHERE id=?", (rid,)).fetchone()
        if config:
            db.execute(
                "UPDATE channel_threads SET allowed_policy_id=? WHERE id=?",
                (json.loads(config[0]).get("allowed_policy_id", "*"), tid),
            )
    return tid


def _thread(self: Channels, db, tid, wid, uid):
    row = db.execute(
        "SELECT * FROM channel_threads WHERE id=? AND workspace_id=?", (tid, wid)
    ).fetchone()
    if not row or row["principal_id"] != uid:
        raise Conflict("Thread does not belong to the initiating principal.")
    if row["state"] not in OPEN or row["deadline"] <= stamp():
        raise Conflict("Thread is closed or expired.")
    self._role(db, uid, wid, write=True)
    for root in db.execute(
        "SELECT * FROM channel_automation_roots WHERE thread_id=?", (tid,)
    ).fetchall():
        if root["kind"] == "routine":
            job = db.execute(
                "SELECT j.state,j.version,r.version AS current_version,r.enabled,r.deleted,r.principal_id FROM routine_jobs j JOIN routines r ON r.id=j.routine_id WHERE j.id=?",
                (root["origin_id"],),
            ).fetchone()
            if (
                not job
                or not job["enabled"]
                or job["deleted"]
                or job["version"] != job["current_version"]
                or job["principal_id"] != uid
                or job["state"] not in {"claimed", "running", "completed"}
            ):
                raise Conflict("Routine no longer authorizes this conversation.")
        else:
            handoffs = db.execute(
                "SELECT h.* FROM handoffs h WHERE correlation_id=?",
                (root["origin_id"],),
            ).fetchall()
            if not handoffs or any(
                h["state"] not in {"accepted", "running", "completed"}
                or h["principal_id"] != uid
                or not db.execute(
                    "SELECT 1 FROM group_members WHERE group_id=? AND bot_id=?",
                    (h["group_id"], h["target_bot_id"]),
                ).fetchone()
                for h in handoffs
            ):
                raise Conflict("Group no longer authorizes this conversation.")
    return row


def _context(self: Channels, db, bid, rid):
    run = db.execute("SELECT * FROM runs WHERE id=? AND bot_id=?", (rid, bid)).fetchone()
    if not run or run["status"] not in ACTIVE_RUNS or run["status"] == "stopping":
        raise Conflict("Run no longer authorizes messaging.")
    wid = db.execute("SELECT workspace_id FROM bot_streams WHERE bot_id=?", (bid,)).fetchone()[0]
    self._authorize(db, run["user_id"], bid, wid)
    source = self._participant(db, bid, wid)
    context = db.execute("SELECT * FROM channel_run_context WHERE run_id=?", (rid,)).fetchone()
    if not context:
        tid = self._new_thread(db, wid, run["user_id"], bid, rid)
        db.execute("INSERT INTO channel_run_context VALUES (?,?,NULL,0)", (rid, tid))
        context = db.execute("SELECT * FROM channel_run_context WHERE run_id=?", (rid,)).fetchone()
    thread = self._thread(db, context["thread_id"], wid, run["user_id"])
    return run, source, context, thread
