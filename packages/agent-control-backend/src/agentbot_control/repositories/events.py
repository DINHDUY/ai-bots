"""bot_events and messages."""

import json
import sqlite3
from typing import Any, TypedDict

from agentbot_control.common import identifier, packed, stamp


class ReplayPage(TypedDict):
    events: list[dict[str, Any]]
    resync_required: bool
    latest_seq: int
    next_seq: int


def replay(db: sqlite3.Connection, bot_id: str, after: int = 0, limit: int = 100) -> ReplayPage:
    stream = db.execute(
        "SELECT seq,floor_seq FROM bot_streams WHERE bot_id=?", (bot_id,)
    ).fetchone()
    if stream is None:
        raise KeyError("Bot stream not found")
    gap = after < stream["floor_seq"] or after > stream["seq"]
    rows = (
        []
        if gap
        else db.execute(
            "SELECT envelope FROM bot_events WHERE bot_id=? AND seq>? ORDER BY seq LIMIT ?",
            (bot_id, after, max(1, min(limit, 1000))),
        ).fetchall()
    )
    events = [json.loads(row[0]) for row in rows]
    return {
        "events": events,
        "resync_required": gap,
        "latest_seq": stream["seq"],
        "next_seq": events[-1]["seq"] if events else after,
    }


def append(db, bot_id, kind, data, *, run_id=None, action_id=None):
    db.execute("UPDATE bot_streams SET seq=seq+1 WHERE bot_id=?", (bot_id,))
    stream = db.execute("SELECT * FROM bot_streams WHERE bot_id=?", (bot_id,)).fetchone()
    from agentbot_control.shared_computers.resolution import computer_for

    computer = computer_for(db, bot_id)
    if run_id:
        event_run = db.execute("SELECT session_id FROM runs WHERE id=?", (run_id,)).fetchone()
        if event_run and event_run[0] is None:
            computer = None
    event = dict(
        schema_version=2,
        event_id=identifier("evt"),
        seq=stream["seq"],
        workspace_id=stream["workspace_id"],
        bot_id=bot_id,
        session_id=computer["id"] if computer else None,
        generation=computer["generation"] if computer else None,
        run_id=run_id,
        action_id=action_id,
        occurred_at=stamp(),
        type=kind,
        data=data,
    )
    db.execute(
        "INSERT INTO bot_events VALUES (?,?,?,?,?)",
        (event["event_id"], bot_id, event["seq"], event["occurred_at"], packed(event)),
    )
    return event


def message(db, message_id, bot_id, role, content, event):
    db.execute(
        "INSERT INTO messages(id,bot_id,seq,role,content,occurred_at) VALUES (?,?,?,?,?,?)",
        (message_id, bot_id, event["seq"], role, content, event["occurred_at"]),
    )
