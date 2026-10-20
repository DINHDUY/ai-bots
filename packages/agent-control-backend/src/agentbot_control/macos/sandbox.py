"""Server-side Mac client; input is possible only with a current durable claim."""

import base64
import time
from datetime import UTC, datetime

from agentbot.interfaces import CaptureImage, CaptureResult, SandboxError, TerminationUnverified
from agentbot_macos.actions import MacAction, Permit
from agentbot_macos.results import ActionResult

from agentbot_control.repositories import macos_devices as rows


class MacSandbox:
    provider = "macos_local"

    def __init__(self, computers, binding):
        self.computers, self.binding = computers, binding
        self.uncertain = False
        self.uncertain_reason = ""
        self.sequence = 0

    def connection(self, write=False):
        conn = self.computers.connection(self.binding["device_id"])
        conn.check(write)
        return conn

    async def approval_protocol(self):
        return 2

    async def observe(self):
        return await self.connection().rpc("observe")

    async def planner(self, operation, **arguments):
        return await self.connection().rpc("planner", {"operation": operation, **arguments})

    async def execute_macos(self, action, *, action_id):
        checked = MacAction.model_validate(action)
        conn = self.connection(True)
        rid = await self.computers.store.database.read(
            lambda db: rows.executing(
                db, action_id, self.binding["session_id"], checked.model_dump()
            )
        )
        permit = Permit(
            action_id=action_id,
            run_id=rid,
            session_id=self.binding["session_id"],
            device_id=self.binding["device_id"],
            console_session=conn.hello.console_session,
            generation=self.binding["generation"],
            epoch=conn.hello.epoch,
            local_revision=conn.hello.revision,
            expires_at=float(time.time() + 8),
            action=checked,
        ).sign(conn.token)
        try:
            result = ActionResult.model_validate(
                await conn.rpc("execute", permit.model_dump())
            ).model_dump()
        except BaseException as exc:
            self.uncertain = True
            self.uncertain_reason = "Mac action outcome unknown; inspect the application and disconnect before continuing"
            raise TerminationUnverified(self.uncertain_reason) from exc
        if result.get("outcome_unknown"):
            self.uncertain = True
            self.uncertain_reason = result.get("text", "Mac action outcome unknown")
            raise TerminationUnverified(self.uncertain_reason)
        return result

    async def capture(self, surface="desktop"):
        if surface != "desktop":
            raise SandboxError("This Mac exposes the Desktop surface")
        value = await self.connection().rpc("capture")
        self.sequence += 1
        return CaptureImage(
            CaptureResult(
                image=base64.b64decode(value["image"], validate=True),
                surface_id="macos:" + self.binding["session_id"],
                surface_kind="desktop",
                width=value["width"],
                height=value["height"],
                captured_at=datetime.fromtimestamp(value["captured_at"], UTC).isoformat(),
                sequence=self.sequence,
                viewport_revision=value["id"],
                transform={k: value[k] for k in ("bounds", "scale_x", "scale_y", "display_id")},
            )
        )

    async def cancel_commands(self):
        conn = self.computers.connections.get(self.binding["device_id"])
        if conn and not conn.closed:
            try:
                await conn.rpc("cancel", timeout=5)
            except Exception:
                if self.uncertain:
                    raise TerminationUnverified(self.uncertain_reason)
        if self.uncertain:
            raise TerminationUnverified(self.uncertain_reason)
