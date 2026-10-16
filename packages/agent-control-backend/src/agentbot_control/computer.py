"""Inspect-only health and authenticated capture services."""

import asyncio
import base64
import os
import time
from collections import OrderedDict
from copy import deepcopy
from datetime import datetime, timedelta

from agentbot.interfaces import SandboxManager
from fastapi import HTTPException, Request

from agentbot_control.authorization import request_bot
from agentbot_control.event_store import packed, sanitized, stamp
from agentbot_control.repositories import computers as computer_rows
from agentbot_control.schemas import Command, Conflict
from agentbot_control.transport import body


class Computers:
    def __init__(
        self,
        store,
        kernel,
        *,
        cloud,
        lifecycle,
        control,
        toolkit,
        bind,
        action_locks,
        workspace_features,
        ensure,
        workspaces,
    ):
        self.store = store
        self.kernel = kernel
        self.cloud = cloud
        self.lifecycle = lifecycle
        self.control = control
        self.toolkit = toolkit
        self.bind = bind
        self.action_locks = action_locks
        self.workspace_features = workspace_features
        self.ensure = ensure
        self.workspaces = workspaces
        self.observers = {}
        self.last_capture = {}
        self.last_files = {}
        self.interval = float(os.getenv("HEALTH_POLL_SECONDS", "10"))
        self.inspection_ttl = 2.0
        self._inspections = OrderedDict()
        self._inspecting = {}

    async def _inspect(self, computer):
        # Scope by the full persisted lifecycle state, including generation.
        key = packed(computer)
        cached = self._inspections.get(key)
        if cached and time.monotonic() - cached[0] < self.inspection_ttl:
            self._inspections.move_to_end(key)
            return deepcopy(cached[1])
        task = self._inspecting.get(key)
        if task is None:

            async def inspect():
                try:
                    report = await asyncio.wait_for(
                        self.kernel.sandboxes.inspect(computer["id"]), 6
                    )
                    report = {**report, "observed_at": stamp()}
                    # Local Windows control/consent is live; do not cache its status.
                    if report.get("provider") not in {"windows_local", "macos_local"}:
                        self._inspections[key] = (time.monotonic(), deepcopy(report))
                        while len(self._inspections) > 256:
                            self._inspections.popitem(last=False)
                    return report
                finally:
                    self._inspecting.pop(key, None)

            task = asyncio.create_task(inspect())
            self._inspecting[key] = task
            # A disconnected HTTP observer must not cancel the monitor's inspection.
            task.add_done_callback(lambda done: None if done.cancelled() else done.exception())
        return deepcopy(await asyncio.shield(task))

    async def shutdown(self):
        tasks = list(self._inspecting.values())
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self._inspections.clear()

    async def observe(self, bot_id, *, _retry=True):
        if self.cloud.selected(bot_id):
            report = self.cloud.report(bot_id)
            if report["computer"]:

                def write():
                    with self.store.transaction() as db:
                        computer_rows.save_health(
                            db,
                            report["computer"]["id"],
                            report["observed_at"],
                            report,
                        )
                        self.store._event(db, bot_id, "computer.health", report)

                await self.store.offload(write)
            return report
        computer = self.store.computer(bot_id)
        if not computer:
            return {"computer": None, "health": "unknown", "capabilities": {}}
        manager = self.kernel.sandboxes
        self.bind(computer)
        report = {
            "lifecycle": computer["status"],
            "services": {},
            "compatible": False,
            "started_at": None,
        }
        try:
            if isinstance(manager, SandboxManager) and computer["status"] != "closed":
                report = await self._inspect(computer)
                current = self.store.computer(bot_id)
                if current != computer:
                    # Retry once after reset/close without serving the old generation.
                    if _retry:
                        return await self.observe(bot_id, _retry=False)
                    return {"computer": current, "health": "unknown", "capabilities": {}}
                report["health"] = (
                    (
                        "healthy"
                        if all(
                            report["services"].get(k)
                            for k in (
                                ("desktop",)
                                if report.get("provider") in {"windows_local", "macos_local"}
                                else ("browser", "desktop")
                            )
                        )
                        else "degraded"
                    )
                    if report["lifecycle"] == "running"
                    else "unavailable"
                )
            else:
                report["health"] = "unknown"
        except Exception:
            report["health"] = "unknown"
        report.setdefault("observed_at", stamp())
        report["stale_after_seconds"] = 30
        report = sanitized(report)

        def write():
            with self.store.transaction() as db:
                changed = computer_rows.save_health(
                    db,
                    computer["id"],
                    report["observed_at"],
                    report,
                    only_if_changed=True,
                )
                if changed:
                    from agentbot_control.shared_computers.resolution import emit

                    emit(self.store, db, bot_id, "computer.health", report, computer["id"])

        await self.store.offload(write)
        idle = float(os.getenv("SESSION_IDLE_SECONDS", "900"))
        retention = self.lifecycle.retention(computer["id"])
        return {
            "computer": computer,
            **report,
            "idle_deadline": (
                datetime.fromisoformat(computer["updated_at"]) + timedelta(seconds=idle)
            ).isoformat(),
            "retention_policy": "close_on_idle",
            **retention,
            "capabilities": {
                "capture": bool(report.get("compatible")),
                "health": bool(report.get("compatible")),
            },
        }

    async def existing(self, bot_id, session_id=None):
        computer = self.store.computer(bot_id)
        if (
            not computer
            or computer["status"] != "running"
            or (session_id and computer["id"] != session_id)
        ):
            raise Conflict("The requested computer is not running or its generation changed.")
        manager = self.kernel.sandboxes
        if not isinstance(manager, SandboxManager):
            raise Conflict("This sandbox does not support computer services.")
        self.bind(computer)
        return computer, await manager.existing(computer["id"])

    async def capture(self, bot_id, surface="browser"):
        lease = self.control.state(bot_id)["lease"]
        recording = self.toolkit.recording(lease["id"]) if lease else None
        if recording and recording["private"]:
            raise Conflict("Captures are disabled during private input.")
        if surface not in {"browser", "desktop"}:
            raise Conflict("Unknown surface.")
        computer, sandbox = await self.existing(bot_id)
        key = (computer["id"], surface)
        if time.monotonic() - self.last_capture.get(key, 0) < 0.5:
            raise Conflict("Capture rate limited; try again shortly.")
        lock = self.action_locks.setdefault(computer["id"], asyncio.Lock())
        if lock.locked():
            raise Conflict("An action owns the surface; wait for its result.")
        async with lock:
            await self.existing(bot_id, computer["id"])
            self.last_capture[key] = time.monotonic()
            image = await sandbox.capture(surface)
            return self.store.record_capture(
                bot_id, None, base64.b64encode(image).decode(), image.metadata
            )

    def history(self, bot_id, surface=None, before=None, before_sequence=None, session_id=None):
        with self.store.transaction() as db:
            return self.store.captures.history_db(
                db, bot_id, surface, before, before_sequence=before_sequence, session_id=session_id
            )

    async def monitor(self):
        while True:
            if not self.workspace_features:
                self.store.health.progressed("computer_monitor")
                await asyncio.sleep(self.interval)
                continue
            for computer in self.store.computers():
                if computer["status"] == "closed":
                    continue
                from agentbot_control.shared_computers.resolution import primary_bot

                bot_id = computer["bot_id"] or primary_bot(self.store, computer.get("workspace_id"))
                if not bot_id:
                    continue
                report = await self.observe(bot_id)
                if report.get("compatible") and report.get("lifecycle") == "running":
                    try:
                        _, sandbox = await self.existing(bot_id)
                        changes = await sandbox.files("changes")
                        revision = (changes["epoch"], changes["sequence"])
                        if self.last_files.get(computer["id"]) != revision:
                            self.last_files[computer["id"]] = revision

                            def write():
                                with self.store.transaction() as db:
                                    from agentbot_control.shared_computers.resolution import emit

                                    emit(
                                        self.store,
                                        db,
                                        bot_id,
                                        "files.changed",
                                        changes,
                                        computer["id"],
                                    )

                            await self.store.offload(write)
                    except Exception:
                        pass
                if (
                    self.observers.get(bot_id, 0)
                    and report["health"] == "healthy"
                    and not self.control.state(bot_id)["lease"]
                ):
                    try:
                        await self.capture(
                            bot_id,
                            "desktop"
                            if report.get("provider") in {"windows_local", "macos_local"}
                            else "browser",
                        )
                    except Exception:
                        pass
            self.store.health.progressed("computer_monitor")
            await asyncio.sleep(self.interval)


def register_computer_routes(app):
    service = app.state.runtime.computers

    @app.get("/api/bots/{bot_id}/computer")
    async def computer(bot_id: str, request: Request):
        user, bot = request_bot(request, bot_id)
        service.ensure(bot)
        report = await service.observe(bot_id)
        try:
            service.workspaces.bot(user.id, bot_id, "write")
            writable = True
        except HTTPException:
            writable = False
        compatible = bool(report.get("compatible"))
        report["capabilities"].update(
            lifecycle=writable,
            remote_control=writable and compatible,
            pty=writable and bool(report.get("services", {}).get("terminal")),
            upload=writable and bool(report.get("services", {}).get("files")),
        )
        from agentbot_control.shared_computers.resolution import bot_blocked, present

        if report.get("computer"):

            def shown():
                with service.store.transaction() as db:
                    return present(report["computer"], db)

            report["computer"] = shown()
        if bot.framework in {"ufo", "open_interface"}:
            report["provider"] = (
                "macos_local" if bot.framework == "open_interface" else "windows_local"
            )
            report["capabilities"].update(
                remote_control=False,
                desktop_takeover=writable,
                lifecycle_actions=["create", "close"],
            )
            report["retention_policy"] = "disconnect_on_idle"
        elif service.cloud.selected(bot_id):
            cloud = service.cloud
            actions = cloud.actions(user, bot_id)
            report["capabilities"].update(lifecycle=bool(actions), lifecycle_actions=actions)
            binding = cloud.binding(bot_id=bot_id)
            if binding and cloud.can_manage(user, bot_id, cloud.profile_for(binding)):
                report["cloud_details"] = cloud.details(binding)
        if bot_blocked(service.store, bot_id):
            report["workspace_computer"] = True
            report["display_name"] = "Shared workspace computer"
            report["capabilities"].update(lifecycle=False, lifecycle_actions=[])
        return report

    @app.get("/api/bots/{bot_id}/captures")
    async def captures(
        bot_id: str,
        request: Request,
        surface: str | None = None,
        before: str | None = None,
        before_sequence: int | None = None,
    ):
        request_bot(request, bot_id)
        return service.history(bot_id, surface, before, before_sequence)

    @app.get("/api/bots/{bot_id}/captures/latest")
    async def latest(bot_id: str, request: Request, surface: str | None = None):
        request_bot(request, bot_id)
        rows = service.history(bot_id, surface)
        if not rows:
            raise HTTPException(404, "No capture available.")
        return rows[0]

    @app.post("/api/bots/{bot_id}/computer/capture")
    async def capture(bot_id: str, request: Request, surface: str = "browser"):
        request_bot(request, bot_id)
        await body(request, Command)
        result = await service.capture(bot_id, surface)
        if not result or result.get("retained") is False:
            raise HTTPException(507, (result or {}).get("reason", "Screenshot not retained."))
        return result
