from __future__ import annotations

import base64
import time

from agentbot.interfaces import (
    CaptureImage,
    CaptureResult,
    SandboxError,
    TerminationUnverified,
)
from agentbot_windows.protocol import Permit, WindowsAction


class WindowsSandbox:
    provider = "windows_local"

    def __init__(self, computers, binding):
        self.computers, self.binding = computers, binding
        self.uncertain = False
        self.uncertain_reason = ""

    def connection(self, write=False):
        conn = self.computers.connection(self.binding["device_id"])
        conn.check(write)
        return conn

    async def approval_protocol(self):
        return 2

    async def observe(self):
        return await self.connection().rpc("observe")

    async def planner(self, operation, **arguments):
        return await self.connection().rpc(
            "planner", {"operation": operation, **arguments}, timeout=90
        )

    async def execute_windows(self, action, *, action_id):
        conn = self.connection(write=True)
        checked = WindowsAction.model_validate(action)
        permit = Permit(
            action_id=action_id,
            session_id=self.binding["session_id"],
            generation=self.binding["generation"],
            epoch=conn.hello.epoch,
            local_revision=conn.hello.revision,
            expires_at=float(time.time() + 8),
            action=checked,
        ).sign(conn.token)
        try:
            result = await conn.rpc("execute", permit.model_dump())
        except BaseException as exc:
            self.uncertain = True
            self.uncertain_reason = (
                f"Windows action outcome unknown: {str(exc) or type(exc).__name__}. "
                "Inspect the application and disconnect this binding before continuing"
            )[:700]
            raise TerminationUnverified(self.uncertain_reason) from exc
        if result.get("outcome_unknown"):
            self.uncertain = True
            self.uncertain_reason = result.get("text", "Windows action outcome is unknown")
            raise TerminationUnverified(self.uncertain_reason)
        return result

    async def capture(self, surface="desktop"):
        if surface != "desktop":
            raise SandboxError("This Windows provider exposes the Desktop surface")
        value = await self.connection().rpc("capture")
        raw = base64.b64decode(value.pop("image"), validate=True)
        return CaptureImage(
            CaptureResult(
                image=raw,
                surface_id=f"windows:{self.binding['session_id']}",
                surface_kind="desktop",
                **value,
            )
        )

    async def cancel_commands(self):
        conn = self.computers.connections.get(self.binding["device_id"])
        if conn and not conn.closed:
            try:
                await conn.rpc("cancel", timeout=5)
            except Exception:
                if self.uncertain:
                    raise TerminationUnverified(
                        self.uncertain_reason or "Reconnect and inspect Windows before resuming"
                    )
        if self.uncertain:
            raise TerminationUnverified(
                self.uncertain_reason
                or "A Windows action may have executed. Reconcile before reconnecting this bot."
            )
