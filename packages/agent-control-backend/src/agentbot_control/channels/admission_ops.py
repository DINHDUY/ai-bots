from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from fastapi import HTTPException

from agentbot_control.channels import OPEN, PENDING
from agentbot_control.schemas import Conflict

if TYPE_CHECKING:
    from agentbot_control.channels import Channels


def _cancel(self: Channels, db, tid, state="cancelled"):
    thread = db.execute("SELECT * FROM channel_threads WHERE id=?", (tid,)).fetchone()
    if not thread or thread["state"] not in OPEN:
        return
    db.execute("UPDATE channel_threads SET state=? WHERE id=?", (state, tid))
    db.execute(
        "UPDATE channel_deliveries SET state=?,reason=? WHERE thread_id=? AND state IN ('queued','blocked')",
        (state, "thread_" + state, tid),
    )
    db.execute(
        "UPDATE channel_continuations SET state=? WHERE thread_id=? AND state IN ('waiting','queued')",
        (state, tid),
    )
    self.event(db, thread["workspace_id"], "thread." + state, {"thread_id": tid})


def cancel(self: Channels, uid, wid, tid):
    self.available()
    with self.store.transaction() as db:
        role = self._role(db, uid, wid, write=True)
        thread = db.execute(
            "SELECT * FROM channel_threads WHERE id=? AND workspace_id=?",
            (tid, wid),
        ).fetchone()
        if not thread or (thread["principal_id"] != uid and role != "owner"):
            raise HTTPException(404, "Thread unavailable.")
        self._cancel(db, tid)
    return {"status": "cancelled"}


def stop_bot(self: Channels, bid, rid=None):
    with self.store.transaction() as db:
        rows = db.execute(
            "SELECT DISTINCT t.id FROM channel_threads t LEFT JOIN channel_continuations c ON c.thread_id=t.id WHERE (t.origin_bot_id=? OR c.bot_id=?) AND t.state IN ('open','waiting_peer')",
            (bid, bid),
        ).fetchall()
        for row in rows:
            self._cancel(db, row[0])


def user_admitted(self: Channels, db, bid):
    for row in db.execute(
        "SELECT DISTINCT thread_id FROM channel_continuations WHERE bot_id=? AND state IN ('waiting','queued')",
        (bid,),
    ).fetchall():
        self._cancel(db, row[0])


def valid_run(self: Channels, db, rid):
    delivery = db.execute("SELECT * FROM channel_deliveries WHERE run_id=?", (rid,)).fetchone()
    try:
        if delivery:
            self._valid_delivery(db, delivery)
        else:
            context = db.execute(
                "SELECT t.* FROM channel_run_context c JOIN channel_threads t ON t.id=c.thread_id WHERE c.run_id=?",
                (rid,),
            ).fetchone()
            if context:
                self._thread(
                    db,
                    context["id"],
                    context["workspace_id"],
                    context["principal_id"],
                )
        return True
    except (Conflict, HTTPException):
        return False


def task(self: Channels, uid, bid):
    self.workspaces.bot(uid, bid)
    with self.store.transaction() as db:
        row = db.execute(
            "SELECT t.id AS thread_id,t.workspace_id,t.state,c.state AS wait_state,c.wait_mode FROM channel_continuations c JOIN channel_threads t ON t.id=c.thread_id WHERE c.bot_id=? ORDER BY c.created_at DESC LIMIT 1",
            (bid,),
        ).fetchone()
        return dict(row) if row else None


def _valid_delivery(self: Channels, db, delivery):
    thread = db.execute(
        "SELECT * FROM channel_threads WHERE id=?", (delivery["thread_id"],)
    ).fetchone()
    self._thread(db, thread["id"], thread["workspace_id"], thread["principal_id"])
    for message in db.execute(
        "SELECT DISTINCT m.id FROM channel_messages m JOIN channel_artifact_grants g ON g.message_id=m.id WHERE m.thread_id=?",
        (thread["id"],),
    ).fetchall():
        self._artifact_context(db, thread["workspace_id"], message[0])
    bot = self._authorize(
        db,
        thread["principal_id"],
        delivery["target_bot_id"],
        thread["workspace_id"],
    )
    self._participant(
        db,
        delivery["target_bot_id"],
        thread["workspace_id"],
        delivery["target_enrollment"],
    )
    if delivery["source_bot_id"]:
        self._authorize(
            db,
            thread["principal_id"],
            delivery["source_bot_id"],
            thread["workspace_id"],
        )
        self._participant(
            db,
            delivery["source_bot_id"],
            thread["workspace_id"],
            delivery["source_enrollment"],
        )
    if delivery["source_run_id"]:
        run = db.execute(
            "SELECT status FROM runs WHERE id=?", (delivery["source_run_id"],)
        ).fetchone()
        if not run or run[0] in {"cancelled", "failed", "interrupted", "stopping"}:
            raise Conflict("Source task was interrupted or stopped.")
    return thread, bot


def admit(self: Channels, db, bot, rid, delivery_id):
    """Called inside the runtime admission transaction, before commit/task creation."""
    delivery = db.execute("SELECT * FROM channel_deliveries WHERE id=?", (delivery_id,)).fetchone()
    if not delivery or delivery["state"] not in PENDING or delivery["target_bot_id"] != bot.id:
        raise Conflict("Delivery no longer authorizes dispatch.")
    thread, _ = self._valid_delivery(db, delivery)
    if thread["runs_used"] >= thread["run_limit"]:
        raise Conflict("budget_exhausted")
    db.execute(
        "UPDATE channel_threads SET runs_used=runs_used+1 WHERE id=?",
        (thread["id"],),
    )
    db.execute(
        "UPDATE channel_threads SET origin_run_id=? WHERE id=? AND origin_run_id IS NULL AND origin_bot_id=?",
        (rid, thread["id"], bot.id),
    )
    db.execute(
        "UPDATE channel_deliveries SET state='admitted',reason=NULL,run_id=? WHERE id=?",
        (rid, delivery_id),
    )
    request_id = delivery["message_id"]
    if delivery["continuation_id"]:
        wait = db.execute(
            "SELECT * FROM channel_continuations WHERE id=?",
            (delivery["continuation_id"],),
        ).fetchone()
        parent = db.execute(
            "SELECT request_message_id FROM channel_run_context WHERE run_id=?",
            (wait["source_run_id"],),
        ).fetchone()
        request_id = parent[0] if parent else None
        db.execute(
            "UPDATE channel_continuations SET state='resumed' WHERE id=?",
            (wait["id"],),
        )
        self.store._event(
            db,
            bot.id,
            "channel.resumed",
            {"thread_id": thread["id"], "status": "running"},
            rid,
        )
    db.execute(
        "INSERT INTO channel_run_context VALUES (?,?,?,?)",
        (rid, thread["id"], request_id, delivery["depth"]),
    )
    self.event(
        db,
        thread["workspace_id"],
        "delivery.admitted",
        {"delivery_id": delivery_id, "thread_id": thread["id"]},
    )


def inherit(self: Channels, db, bot, rid, request_id, trigger):
    """Share budgets and cancellation through group/routine descendants."""
    if trigger not in {"handoff", "routine"}:
        return
    handoff = (
        db.execute("SELECT * FROM handoffs WHERE id=?", (request_id[len("handoff_") :],)).fetchone()
        if request_id.startswith("handoff_")
        else None
    )
    if handoff and handoff["target_bot_id"] != bot.id:
        raise Conflict("Handoff target does not match run admission.")
    parent = (
        db.execute(
            "SELECT * FROM channel_run_context WHERE run_id=?",
            (handoff["source_run_id"],),
        ).fetchone()
        if handoff and handoff["source_run_id"]
        else None
    )
    if parent:
        tid, depth = parent["thread_id"], parent["depth"] + 1
    else:
        entry = db.execute(
            "SELECT * FROM workspace_bot_directory WHERE bot_id=? AND state='enabled'",
            (bot.id,),
        ).fetchone()
        if (
            not self.enabled
            or not entry
            or not self._has_bundle(db, bot.id)
            or not self._channel(db, entry["workspace_id"])["enabled"]
        ):
            return
        origin = handoff["request_id"] if handoff else request_id
        job = (
            db.execute(
                "SELECT j.*,v.definition FROM routine_jobs j JOIN routine_versions v ON v.routine_id=j.routine_id AND v.version=j.version WHERE j.id=?",
                (origin[len("routine_") :],),
            ).fetchone()
            if origin.startswith("routine_")
            else None
        )
        if not handoff and not job:
            return
        kind, origin_id = ("routine", job["id"]) if job else ("group", handoff["correlation_id"])
        root = db.execute(
            "SELECT thread_id FROM channel_automation_roots WHERE kind=? AND origin_id=?",
            (kind, origin_id),
        ).fetchone()
        depth = handoff["hop"] if handoff else 0
        if root:
            tid = root[0]
        else:
            run = db.execute("SELECT user_id FROM runs WHERE id=?", (rid,)).fetchone()
            tid = self._new_thread(db, entry["workspace_id"], run[0], bot.id, rid)
            deadline = (
                handoff["deadline"]
                if handoff
                else (
                    datetime.fromisoformat(job["created_at"])
                    + timedelta(seconds=json.loads(job["definition"]).get("timeout_seconds", 1800))
                ).isoformat()
            )
            db.execute(
                "UPDATE channel_threads SET deadline=MIN(deadline,?),run_limit=? WHERE id=?",
                (deadline, min(8, handoff["budget"]) if handoff else 8, tid),
            )
            db.execute(
                "INSERT INTO channel_automation_roots VALUES (?,?,?)",
                (kind, origin_id, tid),
            )
    run = db.execute("SELECT user_id FROM runs WHERE id=?", (rid,)).fetchone()
    thread = db.execute("SELECT * FROM channel_threads WHERE id=?", (tid,)).fetchone()
    self._thread(db, tid, thread["workspace_id"], run[0])
    if thread["runs_used"] >= thread["run_limit"] or depth > 3:
        raise Conflict("budget_exhausted")
    db.execute("UPDATE channel_threads SET runs_used=runs_used+1 WHERE id=?", (tid,))
    db.execute("INSERT INTO channel_run_context VALUES (?,?,NULL,?)", (rid, tid, depth))


def automation_state(self: Channels, rid):
    with self.store.transaction() as db:
        context = db.execute(
            "SELECT t.state FROM channel_run_context c JOIN channel_threads t ON t.id=c.thread_id WHERE c.run_id=? AND t.messages_used>0",
            (rid,),
        ).fetchone()
        if not context:
            return None
        return (
            "running"
            if context[0] in OPEN
            else "completed"
            if context[0] == "resolved"
            else "failed"
        )
