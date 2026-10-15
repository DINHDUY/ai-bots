"""Owner-operated lifecycle for the one computer a workspace shares."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from typing import Literal

from pydantic import Field

from agentbot_control.common import fingerprint, identifier, packed, stamp
from agentbot_control.repositories import admission
from agentbot_control.schemas import Command, Conflict
from agentbot_control.shared_computers.resolution import (
    emit_workspace,
    open_computer,
    present,
    session_busy,
    set_status,
    settings_row,
)


class WorkspaceLifecycle(Command):
    operation: Literal[
        "create",
        "close",
        "reset",
        "hibernate",
        "resume",
        "keep-warm",
        "attach",
        "start",
        "stop",
        "delete-managed",
    ]
    generation: int = Field(ge=0)
    minutes: int = Field(default=30, ge=1, le=120)
    resource_id: str | None = None
    expected_revision: int | None = None


class SharedLifecycle:
    def __init__(self, store, *, kernel, action_locks, bind, control, stop, tasks):
        self.store = store
        self.kernel = kernel
        self.action_locks = action_locks
        self.bind = bind
        self.control = control
        self.stop = stop
        self.tasks = tasks

    async def command(self, workspace_id, user_id, command: WorkspaceLifecycle):
        if command.operation in {"attach", "start", "stop", "delete-managed"}:
            raise Conflict("This lifecycle action requires a cloud computer.")
        digest = fingerprint(
            {
                "operation": command.operation,
                "generation": command.generation,
                "minutes": command.minutes,
            }
        )
        previous = self._receipt(workspace_id, command.request_id, digest)
        if previous:
            return previous
        settings = self._settings(workspace_id)
        if settings["provider"] != "docker":
            raise Conflict("This workspace computer is a cloud computer.")
        computer = self._open(workspace_id)
        if (computer["generation"] if computer else 0) != command.generation:
            raise Conflict("Computer generation changed.")
        if command.operation != "create" and (not computer or computer["status"] == "closed"):
            raise Conflict("Computer is closed. Explicitly create a new instance.")
        if command.operation == "create" and computer and computer["status"] != "closed":
            raise Conflict("Computer already exists.")
        if command.operation != "keep-warm" and computer and self._busy(computer["id"]):
            raise Conflict(
                "A bot is using the shared computer. Wait for it to finish.",
                code="computer_busy",
            )
        oid = identifier("lifecycle")
        self._begin(workspace_id, command, digest, oid, computer)
        step = "validate"
        try:
            if command.operation == "keep-warm":
                result = self._keep_warm(workspace_id, user_id, computer, command, oid)
            else:
                result = await self._mutate(workspace_id, user_id, computer, command, oid)
                step = result.pop("step", step)
        except Exception:
            current = self._open(workspace_id)
            if current and current["status"] == "provisioning":
                set_status(self.store, None, current["id"], "failed")
            result = {
                "operation_id": oid,
                "status": "failed",
                "operation": command.operation,
                "failed_step": step,
                "detail": "Lifecycle operation failed; inspect the computer before retrying with a new request ID.",
                "computer": self._shown(workspace_id),
            }
        self._finish(workspace_id, oid, result)
        return result

    async def close_idle(self, workspace_id, sid):
        if self._busy(sid):
            return {"status": "retained", "session_id": sid}
        command = WorkspaceLifecycle(
            request_id="idle_" + identifier("idle")[-12:],
            operation="close",
            generation=self._open(workspace_id)["generation"],
        )
        return await self.command(workspace_id, "idle", command)

    def _receipt(self, workspace_id, request_id, digest):
        with self.store.transaction() as db:
            old = db.execute(
                "SELECT * FROM lifecycle_operations WHERE workspace_id=? AND request_id=?",
                (workspace_id, request_id),
            ).fetchone()
        if not old:
            return None
        if old["fingerprint"] != digest:
            raise Conflict("Request ID already used with different arguments.")
        return (
            json.loads(old["result"])
            if old["result"]
            else {"operation_id": old["id"], "status": old["status"]}
        )

    def _settings(self, workspace_id):
        with self.store.transaction() as db:
            return settings_row(db, workspace_id)

    def _open(self, workspace_id):
        with self.store.transaction() as db:
            return open_computer(db, workspace_id)

    def _shown(self, workspace_id):
        with self.store.transaction() as db:
            computer = open_computer(db, workspace_id)
            if not computer:
                row = db.execute(
                    "SELECT * FROM computer_sessions WHERE workspace_id=? ORDER BY generation DESC LIMIT 1",
                    (workspace_id,),
                ).fetchone()
                computer = dict(row) if row else None
            return present(computer, db)

    def _busy(self, sid) -> bool:
        with self.store.transaction() as db:
            return session_busy(db, sid)

    def _begin(self, workspace_id, command, digest, oid, computer):
        with self.store.transaction() as db:
            db.execute(
                "INSERT INTO lifecycle_operations("
                "id,workspace_id,request_id,fingerprint,session_id,operation,status,created_at"
                ") VALUES (?,?,?,?,?,?,'running',?)",
                (
                    oid,
                    workspace_id,
                    command.request_id,
                    digest,
                    computer["id"] if computer else None,
                    command.operation,
                    stamp(),
                ),
            )
            emit_workspace(
                self.store,
                db,
                workspace_id,
                "lifecycle.started",
                {"operation_id": oid, "operation": command.operation},
            )

    def _keep_warm(self, workspace_id, user_id, computer, command, oid):
        if computer["status"] != "running":
            raise Conflict("Only a running computer can stay warm.")
        until = (datetime.now(UTC) + timedelta(minutes=command.minutes)).isoformat()
        with self.store.transaction() as db:
            owner = db.execute(
                "SELECT owner_id FROM workspaces WHERE id=?", (workspace_id,)
            ).fetchone()[0]
            count = db.execute(
                "SELECT COUNT(*) FROM computer_retention r JOIN computer_sessions s ON s.id=r.session_id "
                "LEFT JOIN bots b ON b.id=s.bot_id LEFT JOIN workspaces w ON w.id=s.workspace_id "
                "WHERE COALESCE(b.owner_id, w.owner_id)=? AND r.keep_warm_until>? AND s.id!=?",
                (owner, stamp(), computer["id"]),
            ).fetchone()[0]
            if count >= 2:
                raise Conflict("Keep-warm limit reached (2 computers).")
            db.execute(
                "INSERT INTO computer_retention(session_id,keep_warm_until) VALUES (?,?) "
                "ON CONFLICT(session_id) DO UPDATE SET keep_warm_until=excluded.keep_warm_until,warned=0",
                (computer["id"], until),
            )
            emit_workspace(
                self.store,
                db,
                workspace_id,
                "lifecycle.deadline_changed",
                {"keep_warm_until": until},
            )
        return self._ok(workspace_id, command.operation, oid)

    async def _mutate(self, workspace_id, user_id, computer, command, oid):
        manager = self.kernel.sandboxes
        sid = computer["id"] if computer else "new:" + workspace_id
        async with self.action_locks.setdefault(sid, asyncio.Lock()):
            if command.operation in {"close", "reset"}:
                set_status(self.store, None, sid, "closing")
                await manager.close(sid)
                report = await manager.inspect(sid)
                if report["lifecycle"] != "missing":
                    raise Conflict("Removal not confirmed.")
                set_status(self.store, None, sid, "closed")
                self.control.retire("", sid)
            if command.operation in {"create", "reset"}:
                sid = self._provision(workspace_id, user_id, command.generation + 1)
                self.bind(self._by_id(sid))
                await manager.get_or_create(sid)
                set_status(self.store, None, sid, "running")
            elif command.operation == "hibernate":
                await manager.hibernate(sid)
                set_status(self.store, None, sid, "hibernated")
                self.control.retire("", sid)
                self._retain(sid, (datetime.now(UTC) + timedelta(days=7)).isoformat())
            elif command.operation == "resume":
                if computer["status"] != "hibernated":
                    raise Conflict("Computer is not hibernated.")
                await manager.resume(sid)
                set_status(self.store, None, sid, "running")
        del user_id
        return self._ok(workspace_id, command.operation, oid)

    def _retain(self, sid, until):
        with self.store.transaction() as db:
            db.execute(
                "INSERT INTO computer_retention(session_id,retain_until) VALUES (?,?) "
                "ON CONFLICT(session_id) DO UPDATE SET retain_until=excluded.retain_until,keep_warm_until=NULL",
                (sid, until),
            )

    def _provision(self, workspace_id, user_id, generation):
        sid, now = identifier("computer"), stamp()
        with self.store.transaction() as db:
            owner = db.execute(
                "SELECT owner_id FROM workspaces WHERE id=?", (workspace_id,)
            ).fetchone()[0]
            admission.require_computer(db, None, self.store.admission_limits, owner_id=owner)
            db.execute(
                "INSERT INTO computer_sessions (id,workspace_id,generation,status,created_at,updated_at) "
                "VALUES (?,?,?,'provisioning',?,?)",
                (sid, workspace_id, generation, now, now),
            )
        del user_id
        return sid

    def _by_id(self, sid):
        with self.store.transaction() as db:
            return dict(db.execute("SELECT * FROM computer_sessions WHERE id=?", (sid,)).fetchone())

    def _ok(self, workspace_id, operation, oid):
        return {
            "operation_id": oid,
            "status": "completed",
            "operation": operation,
            "computer": self._shown(workspace_id),
        }

    def _finish(self, workspace_id, oid, result):
        with self.store.transaction() as db:
            db.execute(
                "UPDATE lifecycle_operations SET status=?,result=? WHERE id=?",
                (result["status"], packed(result), oid),
            )
            emit_workspace(self.store, db, workspace_id, "lifecycle." + result["status"], result)
