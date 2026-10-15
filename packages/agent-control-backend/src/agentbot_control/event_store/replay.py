from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from agentbot_control.autopilot import read_state

if TYPE_CHECKING:
    from agentbot_control.event_store import EventStore


def snapshot(self: EventStore, bot_id):
    with self.transaction(write=False) as db:
        captures = self.captures.history_db(db, bot_id, limit=30)
        stream = db.execute("SELECT * FROM bot_streams WHERE bot_id=?", (bot_id,)).fetchone()
        from agentbot_control.shared_computers.resolution import computer_for, present

        computer = present(computer_for(db, bot_id), db)
        run = db.execute(
            "SELECT * FROM runs WHERE bot_id=? ORDER BY created_at DESC LIMIT 1",
            (bot_id,),
        ).fetchone()
        messages = db.execute(
            "SELECT * FROM messages WHERE bot_id=? ORDER BY ordinal DESC LIMIT 201",
            (bot_id,),
        ).fetchall()
        events = db.execute(
            "SELECT envelope FROM bot_events WHERE bot_id=? ORDER BY seq DESC LIMIT 500",
            (bot_id,),
        ).fetchall()
        approvals = db.execute(
            "SELECT * FROM approvals WHERE bot_id=? AND status='pending'", (bot_id,)
        ).fetchall()
        actions = db.execute(
            "SELECT a.id,a.name AS operation,a.status,a.step_id,a.result,a.tool_binding_id,a.tool_binding_revision,a.tool_manifest_digest,p.id AS approval_id,p.detail,p.status AS approval_status,p.revision,p.decided_by,p.decision_source,p.autopilot_revision,p.created_at,p.policy_scope,p.expires_at FROM actions a JOIN approvals p ON p.action_id=a.id WHERE a.run_id=? ORDER BY a.rowid DESC LIMIT 200",
            (run["id"] if run else None,),
        ).fetchall()
        plan = db.execute(
            "SELECT steps FROM run_plans WHERE run_id=?",
            (run["id"] if run else None,),
        ).fetchone()
        return dict(
            schema_version=2,
            autopilot=read_state(db, bot_id),
            tools_revision=(
                db.execute(
                    "SELECT revision FROM bot_tool_config WHERE bot_id=?", (bot_id,)
                ).fetchone()
                or [0]
            )[0],
            selected_tool_count=db.execute(
                "SELECT COUNT(*) FROM bot_tool_bindings WHERE bot_id=? AND enabled=1", (bot_id,)
            ).fetchone()[0],
            bot_id=bot_id,
            workspace_id=stream["workspace_id"],
            snapshot_seq=stream["seq"],
            captures=captures,
            captures_revision=stream["captures_revision"],
            computer=computer,
            run=dict(run) if run else None,
            messages=[dict(m) for m in reversed(messages[:200])],
            messages_before=messages[199]["ordinal"] if len(messages) > 200 else None,
            events=[json.loads(e[0]) for e in reversed(events)],
            observations_truncated=len(events) == 500 or stream["floor_seq"] > 0,
            pending_approvals=[dict(a) for a in approvals],
            actions=[
                {
                    **dict(a),
                    "result": json.loads(a["result"]) if a["result"] else None,
                }
                for a in reversed(actions)
            ],
            plan=json.loads(plan[0]) if plan else None,
            capabilities=self.capabilities,
            health=json.loads(health[0])
            if (
                health := db.execute(
                    "SELECT report FROM computer_health WHERE session_id=?",
                    (computer["id"] if computer else None,),
                ).fetchone()
            )
            else None,
        )


def recover(self: EventStore):
    with self.transaction() as db:
        rows = db.execute(
            "SELECT * FROM runs WHERE status IN ('preparing','running','awaiting_approval','stopping')"
        ).fetchall()
    seen = set()
    for run in rows:
        self.finish(
            run["bot_id"],
            run["id"],
            "interrupted",
            "Control process restarted; execution outcome is unknown.",
        )
        if run["session_id"] and run["session_id"] not in seen:
            seen.add(run["session_id"])
            self.set_computer(run["bot_id"], run["session_id"], "failed")
    return [dict(row) for row in rows]


def prune(self: EventStore, *, prune_captures=True):
    cutoff = (datetime.now(UTC) - timedelta(days=self.retention_days)).isoformat()
    with self.transaction() as db:
        if self.hooks.channels:
            self.hooks.channels.prune(db, cutoff)
        for row in db.execute(
            "SELECT bot_id,MAX(seq) AS floor FROM bot_events WHERE occurred_at<? GROUP BY bot_id",
            (cutoff,),
        ).fetchall():
            db.execute(
                "UPDATE bot_streams SET floor_seq=MAX(floor_seq,?) WHERE bot_id=?",
                (row["floor"], row["bot_id"]),
            )
        db.execute("DELETE FROM bot_events WHERE occurred_at<?", (cutoff,))
    if prune_captures:
        self.captures.sweep()


def messages(self: EventStore, bot_id, before=None, limit=200):
    with self.transaction(write=False) as db:
        rows = db.execute(
            "SELECT * FROM messages WHERE bot_id=? AND ordinal<? ORDER BY ordinal DESC LIMIT ?",
            (bot_id, before or 2**63 - 1, limit + 1),
        ).fetchall()
        return {
            "messages": [dict(r) for r in reversed(rows[:limit])],
            "before": rows[limit - 1]["ordinal"] if len(rows) > limit else None,
        }


def set_computer(self: EventStore, bot_id, sid, status):
    from agentbot_control.shared_computers.resolution import set_status

    set_status(self, bot_id, sid, status)


def computers(self: EventStore):
    with self.transaction() as db:
        return [
            dict(r) for r in db.execute("SELECT * FROM computer_sessions WHERE status!='closed'")
        ]


def capture(self: EventStore, bot_id, cid):
    return self.blobs / cid if self.captures.read(bot_id, cid) is not None else None
