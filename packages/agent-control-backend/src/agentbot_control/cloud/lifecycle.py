from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import TYPE_CHECKING

from agentbot_control.cloud import later
from agentbot_control.event_store import stamp
from agentbot_control.lifecycle import LifecycleCommand
from agentbot_control.schemas import Conflict

if TYPE_CHECKING:
    from agentbot_control.cloud import CloudComputers


async def cleanup(self: CloudComputers, binding):
    """Stop a retired managed host; never delete retained disks automatically."""
    if (
        binding["ownership"] != "managed"
        or binding["active"]
        or binding["cleanup_state"] not in {"pending", "stopping"}
    ):
        return
    driver = self.driver(binding)
    try:
        report = await driver.inspect(binding["resource_id"])
        if report["power"] != "missing":
            self.verify_managed_identity(binding, report)
        if report["power"] in {"stopped", "deallocated", "missing"}:
            with self.store.transaction() as db:
                db.execute(
                    "UPDATE computer_provider_bindings SET cleanup_state=?,observed_state=?,observed_at=? WHERE id=?",
                    (
                        "retained_stopped" if report["power"] != "missing" else "pending_disks",
                        report["power"],
                        stamp(),
                        binding["id"],
                    ),
                )
            return
        if (
            binding["cleanup_state"] == "pending"
            and "stop" in self.profile_for(binding).allowed_operations
        ):
            # This durable phase survives catalog deletion and response loss.
            with self.store.transaction() as db:
                db.execute(
                    "UPDATE computer_provider_bindings SET cleanup_state='stopping',updated_at=? WHERE id=?",
                    (stamp(), binding["id"]),
                )
            await driver.submit("stop", binding["resource_id"], "cleanup-" + binding["id"])
        elif binding["updated_at"] < later(-self.profile_for(binding).operation_timeout_seconds):
            with self.store.transaction() as db:
                db.execute(
                    "UPDATE computer_provider_bindings SET cleanup_state='needs_attention' WHERE id=?",
                    (binding["id"],),
                )
    except Exception:
        # Keep the original resource and phase. Never turn read failures into missing.
        pass


async def loop(self: CloudComputers):
    while True:
        with self.store.transaction() as db:
            operations = [
                dict(r)
                for r in db.execute(
                    "SELECT * FROM cloud_operation_state WHERE phase NOT IN ('completed','failed','outcome_unknown') AND next_poll<=?",
                    (stamp(),),
                )
            ]
            bindings = [
                dict(r)
                for r in db.execute(
                    "SELECT * FROM computer_provider_bindings WHERE active=1 OR (ownership='managed' AND cleanup_state IN ('pending','stopping'))"
                )
            ]
        for key, task in list(self.workers.items()):
            if task.done():
                if not task.cancelled():
                    task.exception()  # consume; step publishes safe diagnostics
                self.workers.pop(key, None)
        busy = {op["binding_id"] for op in operations}
        for op in operations:
            if op["binding_id"] not in self.workers and len(self.workers) < 8:
                self.workers[op["binding_id"]] = asyncio.create_task(self.step(op))
        for binding in bindings:
            if (
                binding["id"] not in busy
                and binding["id"] not in self.workers
                and self.last_observation.get(binding["id"], "") < stamp()
                and len(self.workers) < 8
            ):
                self.last_observation[binding["id"]] = later(30)
                self.workers[binding["id"]] = asyncio.create_task(
                    self.observe_binding(binding) if binding["active"] else self.cleanup(binding)
                )
        self.store.health.progressed("cloud_reconciliation")
        await asyncio.sleep(2)


def start(self: CloudComputers):
    self.pump_task = self.store.health.start(
        "cloud_reconciliation", self.loop(), timeout=30, required=False
    )


async def shutdown(self: CloudComputers):
    if self.pump_task:
        self.pump_task.cancel()
    for task in self.workers.values():
        task.cancel()
    await asyncio.gather(
        *(list(self.workers.values()) + ([self.pump_task] if self.pump_task else [])),
        return_exceptions=True,
    )
    self.workers.clear()
    await self.agents.shutdown()


async def retire(
    self: CloudComputers, bot_id, request_id, expected=None, *, idle=False, actor=None
):
    binding = self.binding(bot_id=bot_id)
    if not binding:
        return {"status": "closed", "session_id": expected}
    if expected and binding["session_id"] != expected:
        raise Conflict("Cloud session changed.")
    profile = self.profile_for(binding)
    if idle and (profile.idle_policy != "stop" or binding["observed_state"] != "running"):
        return {"status": "retained", "session_id": binding["session_id"]}
    with self.store.transaction() as db:
        user = db.execute(
            "SELECT id,username FROM users WHERE id=?", (binding["owner_id"],)
        ).fetchone()
    bot = self.workspaces.bot(binding["owner_id"], bot_id, "read")
    return await self.admit(
        actor or SimpleNamespace(**dict(user)),
        bot,
        "stop" if idle else "close",
        LifecycleCommand(request_id=request_id, generation=binding["generation"]),
    )
