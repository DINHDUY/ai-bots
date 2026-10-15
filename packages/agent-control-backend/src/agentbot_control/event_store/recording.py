from __future__ import annotations

import base64
import logging
from typing import TYPE_CHECKING

from agentbot_control.common import (
    packed,
    protected,
    sanitized,
    stamp,
)
from agentbot_control.repositories import approvals as approval_rows
from agentbot_control.schemas import ACTIVE_RUNS

if TYPE_CHECKING:
    from agentbot_control.event_store import EventStore


def record_frame(self: EventStore, bot_id, rid, frame, secrets=()):
    frame = sanitized(frame, secrets)
    if frame.get("event") == "telemetry":
        try:
            with self.transaction() as db:
                self._event(db, bot_id, "run.metrics", frame.get("data", {}), rid)
        except Exception:
            # Diagnostic writes must never prevent action/worker cleanup.
            logging.getLogger("agentbot_control.event_store").warning(
                "Unable to persist run metrics", exc_info=True
            )
        return
    if frame.get("event") == "artifact_written" and protected(
        frame.get("meta", {}).get("path", "")
    ):
        frame["meta"]["preview"] = ""
        frame["meta"]["protected"] = True
    with self.transaction() as db:
        if frame.get("type") == "RESULT":
            if frame.get("payload"):
                self._message(db, bot_id, "assistant", frame["payload"], rid)
            return
        if frame.get("type") == "SCREENSHOT_CAPTURE":
            # Capture handling runs before string truncation in record_capture.
            return
        if frame.get("event") == "plan_updated":
            db.execute(
                "INSERT INTO run_plans VALUES (?,?,?) ON CONFLICT(run_id) DO UPDATE SET steps=excluded.steps,updated_at=excluded.updated_at",
                (rid, packed(frame["steps"]), stamp()),
            )
            self._event(db, bot_id, "plan.updated", {"steps": frame["steps"]}, rid)
        elif frame.get("type") == "TOOL_CALL":
            self._event(
                db,
                bot_id,
                "observation",
                {"frame": frame, "legacy_only": True},
                rid,
            )
        else:
            self._event(db, bot_id, "observation", {"frame": frame}, rid)


def record_capture(self: EventStore, bot_id, rid, payload, metadata=None):
    if len(payload) > 6 * 1024 * 1024:
        return
    try:
        raw = base64.b64decode(payload, validate=True)
    except ValueError:
        return
    if not raw.startswith(b"\x89PNG") or len(raw) > 4 * 1024 * 1024:
        return
    metadata = sanitized(metadata or {})
    if metadata:
        import struct

        if len(raw) < 24:
            return
        width, height = struct.unpack(">II", raw[16:24])
        if not 0 < width <= 4096 or not 0 < height <= 4096 or width * height > 16777216:
            return
        if metadata.get("width") != width or metadata.get("height") != height:
            return
    return self.captures.store_image(bot_id, rid, raw, metadata)


def _resolve(
    self: EventStore,
    db,
    row,
    status,
    user_id=None,
    *,
    decision_source=None,
    autopilot_revision=None,
):
    if decision_source is None and user_id is not None:
        decision_source = (
            "policy"
            if row["policy_id"]
            else "observation"
            if user_id == "system:observation"
            else "manual"
        )
    if not approval_rows.resolve(db, row, status, user_id, decision_source, autopilot_revision):
        return
    self._event(
        db,
        row["bot_id"],
        "approval.resolved",
        {
            "approval_id": row["id"],
            "status": status,
            "revision": row["revision"] + 1,
            "decided_by": user_id,
            "decision_source": decision_source,
            "autopilot_revision": autopilot_revision,
            "action": row["action"],
            "detail": row["detail"],
            "created_at": row["created_at"],
            "policy_id": row["policy_id"],
            "policy_version": row["policy_version"],
        },
        row["run_id"],
        row["action_id"],
    )


def finish(self: EventStore, bot_id, rid, status, outcome=None):
    with self.transaction() as db:
        run = db.execute("SELECT * FROM runs WHERE id=?", (rid,)).fetchone()
        if not run or run["status"] not in ACTIVE_RUNS:
            return
        for row in db.execute(
            "SELECT * FROM approvals WHERE run_id=? AND status='pending'", (rid,)
        ).fetchall():
            self._resolve(db, row, "cancelled" if status != "interrupted" else "expired")
        db.execute(
            "UPDATE runs SET status=?,outcome=?,updated_at=? WHERE id=?",
            (status, outcome, stamp(), rid),
        )
        db.execute(
            "UPDATE computer_sessions SET updated_at=? WHERE id=?",
            (stamp(), run["session_id"]),
        )
        for action in db.execute(
            "SELECT * FROM actions WHERE run_id=? AND status IN ('authorized','executing')",
            (rid,),
        ).fetchall():
            unknown = action["status"] == "executing"
            data = {
                "ok": False,
                "outcome_unknown": unknown,
                "cancelled": not unknown,
                "operation": action["name"],
                "exit_code": None,
                "stderr": "Execution was interrupted; outcome unknown."
                if unknown
                else "Run ended before dispatch.",
                "started_at": action["started_at"],
                "ended_at": stamp(),
            }
            db.execute(
                "UPDATE actions SET status=?,result=?,ended_at=? WHERE id=?",
                (
                    "outcome_unknown" if unknown else "cancelled",
                    packed(data),
                    stamp(),
                    action["id"],
                ),
            )
            self._event(db, bot_id, "action.failed", data, rid, action["id"])
        self._event(
            db,
            bot_id,
            "run.finished",
            {
                "status": status,
                "outcome": outcome,
                "failed_actions": db.execute(
                    "SELECT COUNT(*) FROM actions WHERE run_id=? AND status IN ('failed','cancelled','outcome_unknown')",
                    (rid,),
                ).fetchone()[0],
            },
            rid,
        )


def request_stop(self: EventStore, bot_id, rid, request_id):
    body = dict(operation="stop", run_id=rid)
    with self.transaction() as db:
        previous = self._receipt(db, bot_id, request_id, body)
        if previous:
            return previous
        row = db.execute("SELECT * FROM runs WHERE id=? AND bot_id=?", (rid, bot_id)).fetchone()
        if not row:
            raise KeyError("Run not found.")
        if row["status"] in ACTIVE_RUNS:
            for approval in db.execute(
                "SELECT * FROM approvals WHERE run_id=? AND status='pending'",
                (rid,),
            ).fetchall():
                self._resolve(db, approval, "cancelled")
            db.execute(
                "UPDATE runs SET status='stopping',updated_at=? WHERE id=?",
                (stamp(), rid),
            )
            self._event(db, bot_id, "run.stopping", {"status": "stopping"}, rid)
        response = dict(
            run_id=rid,
            status="stopping" if row["status"] in ACTIVE_RUNS else row["status"],
        )
        self._save_receipt(db, bot_id, request_id, body, response)
        return response
