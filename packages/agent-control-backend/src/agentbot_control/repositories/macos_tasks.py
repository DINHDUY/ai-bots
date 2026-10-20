"""TaskStar linkage shares the run-admission transaction and survives bot deletion."""

import json
import time
from contextvars import ContextVar

from agentbot_macos.protocol import digest
from agentbot_macos.taskstar import TaskAssignment
from fastapi import HTTPException

from agentbot_control.schemas import Conflict

submission: ContextVar[TaskAssignment | None] = ContextVar("macos_task_submission", default=None)


def previous(db, owner, task):
    row = db.execute(
        "SELECT * FROM macos_task_links WHERE owner_id=? AND producer=? AND task_id=?",
        (owner, task.producer, task.task_id),
    ).fetchone()
    if row and row["input_digest"] != digest(task.model_dump()):
        raise Conflict("TaskStar identity reused with changed input")
    return dict(row) if row else None


def attach(db, owner, bot_id, run_id):
    task = submission.get()
    if task is None:
        return
    if previous(db, owner, task):
        raise Conflict("TaskStar was already admitted")
    db.execute(
        "INSERT INTO macos_task_links VALUES (?,?,?,?,?,?,?,?,?)",
        (
            owner,
            task.producer,
            task.task_id,
            task.request_id,
            bot_id,
            task.device_id,
            run_id,
            digest(task.model_dump()),
            time.time() + task.timeout,
        ),
    )


def deadline(db, run_id):
    row = db.execute("SELECT deadline FROM macos_task_links WHERE run_id=?", (run_id,)).fetchone()
    return max(0.001, row[0] - time.time()) if row else None


def status(db, owner, request_id, bot_id=None):
    row = db.execute(
        "SELECT * FROM macos_task_links WHERE owner_id=? AND request_id=?", (owner, request_id)
    ).fetchone()
    if not row or (bot_id is not None and row["bot_id"] != bot_id):
        raise HTTPException(404, "TaskStar receipt not found")
    run = db.execute("SELECT status,outcome FROM runs WHERE id=?", (row["run_id"],)).fetchone()
    uncertain = db.execute(
        "SELECT 1 FROM actions WHERE run_id=? AND status IN ('unknown','outcome_unknown','executing')",
        (row["run_id"],),
    ).fetchone()
    active = bool(
        run and run["status"] in {"preparing", "running", "awaiting_approval", "stopping"}
    )
    state = (
        "running"
        if active
        else "outcome_unknown"
        if uncertain
        else "completed"
        if run and run["status"] == "completed"
        else "cancelled"
        if run and run["status"] == "cancelled"
        else "failed"
    )
    text = (
        run["outcome"]
        if run
        else "Historical task retained after workspace removal; it cannot be replayed"
    )
    if isinstance(text, str):
        try:
            text = json.loads(text)
        except ValueError:
            pass
    return {
        "task_id": row["task_id"],
        "request_id": row["request_id"],
        "run_id": row["run_id"],
        "state": state,
        "text": str(text or state)[:4000],
        "effect_observed": state == "completed",
        "retryable": False,
    }
