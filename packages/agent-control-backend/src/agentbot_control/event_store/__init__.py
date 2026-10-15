"""Transactional run state and an ordered durable event log.

Subscribers read committed pages instead of owning in-memory execution queues.
"""

from __future__ import annotations

import base64
import json
import logging
import uuid
from contextlib import contextmanager
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from pathlib import Path

from agentbot_control.autopilot import read_state
from agentbot_control.capture_retention import CaptureRetention
from agentbot_control.common import (
    fingerprint,
    identifier,
    packed,
    protected,
    sanitized,
    stamp,
)
from agentbot_control.db import Database
from agentbot_control.hooks import StoreHooks
from agentbot_control.repositories import admission
from agentbot_control.repositories import approvals as approval_rows
from agentbot_control.repositories import events as event_rows
from agentbot_control.repositories import receipts as receipt_rows
from agentbot_control.repositories import runs as run_rows
from agentbot_control.repositories import workspaces as workspace_rows
from agentbot_control.schemas import ACTIVE_RUNS, CAPABILITIES, Conflict
from agentbot_control.supervision import WorkerHealth


class EventStore:
    def __init__(
        self,
        path: Path,
        *,
        retention_days=30,
        blob_limit=256 * 1024 * 1024,
        hooks: StoreHooks | None = None,
        capabilities: dict | None = None,
        db: Database | None = None,
    ):
        self.hooks = hooks or StoreHooks()
        self.health = WorkerHealth()
        self.admission_limits = admission.AdmissionLimits.from_environment()
        self.capabilities = dict(capabilities or CAPABILITIES)
        self.database = db or Database(path)
        self.path = self.database.path
        self.blobs = self.path.with_suffix(".blobs")
        self.blobs.mkdir(parents=True, exist_ok=True)
        self.retention_days = retention_days
        if blob_limit < 1:
            raise ValueError("WORKSPACE_BLOB_LIMIT_BYTES must be positive.")
        self.blob_limit = blob_limit
        self.lock = self.database.lock
        self.db = self.database.connection
        with self.transaction() as connection:
            connection.execute(
                "INSERT OR IGNORE INTO runtime_settings VALUES ('deployment', ?)",
                (uuid.uuid4().hex[:16],),
            )
            self.deployment = connection.execute(
                "SELECT value FROM runtime_settings WHERE key='deployment'"
            ).fetchone()[0]
            for user in connection.execute("SELECT id FROM users").fetchall():
                self._workspace(connection, user[0])

        self.captures = CaptureRetention(self)

    async def offload(self, fn):
        """Run a synchronous store operation on the single database worker."""
        return await self.database.offload(fn)

    @contextmanager
    def transaction(self, *, write=True):
        with self.database.transaction(write=write) as connection:
            yield connection

    def _workspace(self, db, user_id):
        return workspace_rows.personal(db, user_id)

    def workspace(self, user_id):
        with self.transaction() as db:
            return self._workspace(db, user_id)

    def ensure_bot(self, bot, history):
        return admission_ops.ensure_bot(self, bot, history)

    def _event(self, db, bot_id, kind, data, run_id=None, action_id=None):
        event = event_rows.append(db, bot_id, kind, data, run_id=run_id, action_id=action_id)
        self.database.changed(bot_id)
        if self.hooks.projector:
            self.hooks.projector.project(db, event)
        if self.hooks.channels and kind in {
            "control.waiting_for_safe_point",
            "computer.local_paused",
        }:
            self.hooks.channels.user_admitted(db, bot_id)
        return event

    def _message(self, db, bot_id, role, content, run_id):
        message = dict(id=identifier("msg"), role=role, content=content)
        event = self._event(db, bot_id, "message.created", message, run_id)
        event_rows.message(db, message["id"], bot_id, role, content, event)

    def _receipt(self, db, bot_id, request_id, body):
        row = receipt_rows.find(db, bot_id, request_id)
        if row:
            if row["fingerprint"] != fingerprint(body):
                raise Conflict("Request ID was already used for a different command.")
            return json.loads(row["response"])

    def receipt(self, bot_id, request_id, body):
        with self.transaction() as db:
            return self._receipt(db, bot_id, request_id, body)

    def _save_receipt(self, db, bot_id, request_id, body, response):
        receipt_rows.save(db, bot_id, request_id, body, response)

    def admit(
        self,
        bot,
        user_id,
        request_id,
        prompt,
        trigger="user",
        secrets=(),
        attachments=(),
        run_mode="computer",
        channel_delivery_id=None,
        allowed_policy_id="*",
    ):
        return admission_ops.admit(
            self,
            bot,
            user_id,
            request_id,
            prompt,
            trigger,
            secrets,
            attachments,
            run_mode,
            channel_delivery_id,
            allowed_policy_id,
        )

    def _active(self, db, bot_id):
        return run_rows.active(db, bot_id)

    def active(self, bot_id):
        with self.transaction() as db:
            row = self._active(db, bot_id)
            return dict(row) if row else None

    def run(self, bot_id, run_id):
        with self.transaction() as db:
            row = db.execute(
                "SELECT * FROM runs WHERE id=? AND bot_id=?", (run_id, bot_id)
            ).fetchone()
            return dict(row) if row else None

    def computer(self, bot_id):
        with self.transaction() as db:
            from agentbot_control.shared_computers.resolution import computer_for

            return computer_for(db, bot_id)

    def ready(self, bot_id, rid):
        return admission_ops.ready(self, bot_id, rid)

    def record_frame(self, bot_id, rid, frame, secrets=()):
        return recording.record_frame(self, bot_id, rid, frame, secrets)

    def record_capture(self, bot_id, rid, payload, metadata=None):
        return recording.record_capture(self, bot_id, rid, payload, metadata)

    def _resolve(
        self,
        db,
        row,
        status,
        user_id=None,
        *,
        decision_source=None,
        autopilot_revision=None,
    ):
        return recording._resolve(
            self,
            db,
            row,
            status,
            user_id,
            decision_source=decision_source,
            autopilot_revision=autopilot_revision,
        )

    def finish(self, bot_id, rid, status, outcome=None):
        return recording.finish(self, bot_id, rid, status, outcome)

    def request_stop(self, bot_id, rid, request_id):
        return recording.request_stop(self, bot_id, rid, request_id)

    def set_computer(self, bot_id, sid, status):
        return replay.set_computer(self, bot_id, sid, status)

    def messages(self, bot_id, before=None, limit=200):
        return replay.messages(self, bot_id, before, limit)

    def snapshot(self, bot_id):
        return replay.snapshot(self, bot_id)

    def events(self, bot_id, after=0, limit=100) -> event_rows.ReplayPage:
        with self.transaction(write=False) as db:
            return event_rows.replay(db, bot_id, after, limit)

    def recover(self):
        return replay.recover(self)

    def computers(self):
        return replay.computers(self)

    def capture(self, bot_id, cid):
        return replay.capture(self, bot_id, cid)

    def prune(self, *, prune_captures=True):
        return replay.prune(self, prune_captures=prune_captures)


from agentbot_control.event_store import admission_ops, recording, replay

__all__ = [
    "ACTIVE_RUNS",
    "CAPABILITIES",
    "CaptureRetention",
    "Conflict",
    "Database",
    "EventStore",
    "Path",
    "StoreHooks",
    "UTC",
    "WorkerHealth",
    "admission_ops",
    "approval_rows",
    "asdict",
    "base64",
    "contextmanager",
    "datetime",
    "event_rows",
    "fingerprint",
    "identifier",
    "json",
    "logging",
    "packed",
    "protected",
    "read_state",
    "receipt_rows",
    "recording",
    "replay",
    "run_rows",
    "sanitized",
    "stamp",
    "timedelta",
    "uuid",
    "workspace_rows",
]
