"""Explicit Docker lifecycle with durable command identity and conservative recovery."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agentbot.kernel import EngineRuntimeManager

    from agentbot_control.control import Control
    from agentbot_control.event_store import EventStore
    from agentbot_control.ports import StopRun
    from agentbot_control.windows import WindowsComputers

import json
from datetime import UTC, datetime, timedelta
from typing import Literal

from fastapi import Request
from fastapi.responses import JSONResponse
from pydantic import Field

from agentbot_control.authorization import request_bot
from agentbot_control.event_store import fingerprint, identifier, packed, stamp
from agentbot_control.repositories import admission
from agentbot_control.schemas import Command, Conflict
from agentbot_control.transport import body


class LifecycleCommand(Command):
    generation: int = Field(ge=0)
    minutes: int = Field(default=30, ge=1, le=120)


class Lifecycle:
    def __init__(
        self,
        store: EventStore,
        *,
        action_locks: dict[str, asyncio.Lock],
        bind: Callable[[dict], None],
        control: Control,
        kernel: EngineRuntimeManager,
        mutex: Callable[[str], asyncio.Lock],
        stop: StopRun,
        tasks: dict[str, asyncio.Task],
        windows: WindowsComputers,
    ) -> None:
        self.store = store
        self.action_locks = action_locks
        self.bind = bind
        self.control = control
        self.kernel = kernel
        self.mutex = mutex
        self.stop = stop
        self.tasks = tasks
        self.windows = windows

    def retention(self, sid):
        with self.store.transaction() as db:
            row = db.execute(
                "SELECT * FROM computer_retention WHERE session_id=?", (sid,)
            ).fetchone()
        return dict(row) if row else {}

    async def command(self, bot_id, operation, command):
        from agentbot_control.shared_computers.resolution import bot_blocked

        if bot_blocked(self.store, bot_id):
            raise Conflict(
                "This workspace uses one shared computer. Manage it from workspace settings.",
                code="workspace_computer",
            )
        with self.store.transaction() as db:
            native = db.execute("SELECT framework FROM bots WHERE id=?", (bot_id,)).fetchone()
        if native and native[0] == "ufo" and not self.windows.config(bot_id):
            raise Conflict("Select a paired Windows computer in bot settings first.")
        if self.windows.config(bot_id) and operation not in {"create", "close"}:
            raise Conflict("Personal Windows computers support connect/disconnect only.")
        async with self.mutex(bot_id):
            value = {
                "operation": operation,
                "generation": command.generation,
                "minutes": command.minutes,
            }
            digest = fingerprint(value)
            with self.store.transaction() as db:
                old = db.execute(
                    "SELECT * FROM lifecycle_operations WHERE bot_id=? AND request_id=?",
                    (bot_id, command.request_id),
                ).fetchone()
            if old:
                if old["fingerprint"] != digest:
                    raise Conflict("Request ID already used with different arguments.")
                return (
                    json.loads(old["result"])
                    if old["result"]
                    else {"operation_id": old["id"], "status": old["status"]}
                )
            computer = self.store.computer(bot_id)
            if (computer["generation"] if computer else 0) != command.generation:
                raise Conflict("Computer generation changed.")
            if operation != "create" and (not computer or computer["status"] == "closed"):
                raise Conflict("Computer is closed. Explicitly create a new instance.")
            if operation == "create" and computer and computer["status"] != "closed":
                raise Conflict("Computer already exists.")
            oid = identifier("lifecycle")
            with self.store.transaction() as db:
                db.execute(
                    "INSERT INTO lifecycle_operations (id,bot_id,request_id,fingerprint,session_id,operation,status,result,created_at) VALUES (?,?,?,?,?,?,'running',NULL,?)",
                    (
                        oid,
                        bot_id,
                        command.request_id,
                        digest,
                        computer["id"] if computer else None,
                        operation,
                        stamp(),
                    ),
                )
                self.store._event(
                    db,
                    bot_id,
                    "lifecycle.started",
                    {"operation_id": oid, "operation": operation},
                )
            step = "validate"
            try:
                if operation == "keep-warm":
                    if computer["status"] != "running":
                        raise Conflict("Only a running computer can stay warm.")
                    with self.store.transaction() as db:
                        count = db.execute(
                            "SELECT COUNT(*) FROM computer_retention r JOIN computer_sessions s ON s.id=r.session_id JOIN bots b ON b.id=s.bot_id WHERE b.owner_id=(SELECT owner_id FROM bots WHERE id=?) AND r.keep_warm_until>? AND s.id!=?",
                            (bot_id, stamp(), computer["id"]),
                        ).fetchone()[0]
                        if count >= 2:
                            raise Conflict("Keep-warm limit reached (2 computers).")
                        until = (datetime.now(UTC) + timedelta(minutes=command.minutes)).isoformat()
                        db.execute(
                            "INSERT INTO computer_retention(session_id,keep_warm_until) VALUES (?,?) ON CONFLICT(session_id) DO UPDATE SET keep_warm_until=excluded.keep_warm_until,warned=0",
                            (computer["id"], until),
                        )
                        self.store._event(
                            db,
                            bot_id,
                            "lifecycle.deadline_changed",
                            {"keep_warm_until": until},
                        )
                else:
                    step = "stop_work"
                    run = self.store.active(bot_id)
                    if run:
                        self.stop(bot_id, run["id"], identifier("lifecycle_stop"))
                        task = self.tasks.get(run["id"])
                        if task:
                            try:
                                await asyncio.wait_for(asyncio.shield(task), 30)
                            except asyncio.CancelledError:
                                if not task.done():
                                    raise
                        if self.store.active(bot_id):
                            raise Conflict("Run termination is not verified.")
                    lease = self.control.state(bot_id)["lease"]
                    if lease:
                        try:
                            await self.control.release_by_id(lease["id"])
                        except Exception:
                            if operation not in {"close", "reset", "hibernate"}:
                                raise
                    manager = self.kernel.sandboxes
                    sid = computer["id"] if computer else "new:" + bot_id
                    async with self.action_locks.setdefault(sid, asyncio.Lock()):
                        if operation in {"close", "reset"}:
                            step = "remove_old_instance"
                            self.store.set_computer(bot_id, sid, "closing")
                            await manager.close(sid)
                            report = await manager.inspect(sid)
                            if report["lifecycle"] != "missing":
                                raise Conflict("Removal not confirmed.")
                            self.store.set_computer(bot_id, sid, "closed")
                            if lease:
                                self.control.retire(bot_id, sid)
                        if operation in {"create", "reset"}:
                            step = "provision_new_instance"
                            sid, now = identifier("computer"), stamp()
                            generation = command.generation + 1
                            with self.store.transaction() as db:
                                admission.require_computer(db, bot_id, self.store.admission_limits)
                                db.execute(
                                    "INSERT INTO computer_sessions (id,bot_id,generation,status,created_at,updated_at) VALUES (?,?,?,'provisioning',?,?)",
                                    (sid, bot_id, generation, now, now),
                                )
                            self.bind(self.store.computer(bot_id))
                            await manager.get_or_create(sid)
                            self.store.set_computer(bot_id, sid, "running")
                        elif operation == "hibernate":
                            step = "stop_container"
                            await manager.hibernate(sid)
                            self.store.set_computer(bot_id, sid, "hibernated")
                            if lease:
                                self.control.retire(bot_id, sid)
                            with self.store.transaction() as db:
                                until = (datetime.now(UTC) + timedelta(days=7)).isoformat()
                                db.execute(
                                    "INSERT INTO computer_retention(session_id,retain_until) VALUES (?,?) ON CONFLICT(session_id) DO UPDATE SET retain_until=excluded.retain_until,keep_warm_until=NULL",
                                    (sid, until),
                                )
                        elif operation == "resume":
                            if computer["status"] != "hibernated":
                                raise Conflict("Computer is not hibernated.")
                            step = "start_retained_instance"
                            await manager.resume(sid)
                            self.store.set_computer(bot_id, sid, "running")
                        if operation in {"hibernate", "resume"}:
                            with self.store.transaction() as db:
                                db.execute(
                                    "INSERT INTO computer_control(session_id,paused,fence) VALUES (?,1,1) ON CONFLICT(session_id) DO UPDATE SET paused=1,fence=fence+1",
                                    (sid,),
                                )
                result = {
                    "operation_id": oid,
                    "status": "completed",
                    "operation": operation,
                    "computer": self.store.computer(bot_id),
                }
            except Exception:
                current = self.store.computer(bot_id)
                if current and current["status"] == "provisioning":
                    self.store.set_computer(bot_id, current["id"], "failed")
                result = {
                    "operation_id": oid,
                    "status": "failed",
                    "operation": operation,
                    "failed_step": step,
                    "detail": "Lifecycle operation failed; inspect the computer before retrying with a new request ID.",
                    "computer": self.store.computer(bot_id),
                }
            with self.store.transaction() as db:
                db.execute(
                    "UPDATE lifecycle_operations SET status=?,result=? WHERE id=?",
                    (result["status"], packed(result), oid),
                )
                self.store._event(db, bot_id, "lifecycle." + result["status"], result)
            return result

    def recover(self):
        with self.store.transaction() as db:
            rows = db.execute(
                "SELECT * FROM lifecycle_operations WHERE status='running' AND id NOT IN (SELECT operation_id FROM cloud_operation_state)"
            ).fetchall()
            for row in rows:
                result = {
                    "operation_id": row["id"],
                    "status": "interrupted",
                    "operation": row["operation"],
                    "detail": "Control restarted. Inspect reconciled state; the command will not automatically repeat.",
                }
                db.execute(
                    "UPDATE lifecycle_operations SET status='interrupted',result=? WHERE id=?",
                    (packed(result), row["id"]),
                )
                if row["bot_id"]:
                    self.store._event(db, row["bot_id"], "lifecycle.interrupted", result)
                elif row["workspace_id"]:
                    from agentbot_control.shared_computers.resolution import emit_workspace

                    emit_workspace(
                        self.store, db, row["workspace_id"], "lifecycle.interrupted", result
                    )


def register_lifecycle_routes(app):
    service = app.state.runtime.lifecycle

    @app.post("/api/bots/{bot_id}/lifecycle/{operation}")
    async def change(
        bot_id: str,
        operation: Literal[
            "create",
            "close",
            "reset",
            "hibernate",
            "resume",
            "keep-warm",
            "start",
            "stop",
            "delete-managed",
        ],
        request: Request,
    ):
        if app.state.runtime.shared_computers.blocks(bot_id):
            raise Conflict(
                "This workspace uses one shared computer. Manage it from workspace settings.",
                code="workspace_computer",
            )
        if app.state.runtime.cloud.selected(bot_id):
            user, bot = app.state.runtime.cloud.actor(request, bot_id)
            result = await app.state.runtime.cloud.admit(
                user, bot, operation, await body(request, LifecycleCommand)
            )
            return JSONResponse(result, status_code=202 if result["status"] == "accepted" else 200)
        if operation in {"start", "stop", "delete-managed"}:
            raise Conflict("This lifecycle action requires a cloud computer.")
        _, bot = request_bot(request, bot_id)
        app.state.runtime.ensure(bot)
        return await service.command(bot_id, operation, await body(request, LifecycleCommand))
