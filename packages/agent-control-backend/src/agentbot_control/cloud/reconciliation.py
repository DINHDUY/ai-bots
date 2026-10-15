from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agentbot_control.cloud import CloudComputers


async def polling(self: CloudComputers, op, binding, operation, driver, profile):
    await driver.poll_error(op["operation_id"])
    report = await self.observe_binding(binding)
    if operation in {"create", "start"} and report["power"] == "running":
        self.verify_resource(binding, report)
        self.update(
            op,
            "connecting",
            error_code=None,
            detail="Azure is running; waiting for the host service.",
        )
    elif operation == "stop" and report["power"] in {
        "stopped",
        "deallocated",
    }:
        conn = self.agents.connections.get(binding["id"])
        if conn:
            await conn.disconnect()
        self.store.set_computer(binding["bot_id"], binding["session_id"], "hibernated")
        with self.store.transaction() as db:
            db.execute(
                "UPDATE computer_provider_bindings SET status='stopped' WHERE id=?",
                (binding["id"],),
            )
        self.clients.pop(binding["id"], None)
        self.finish(
            op,
            detail="Compute stopped. Disks and workspace data remain; resume the agent separately after starting.",
        )
    elif operation == "delete-managed" and report["power"] == "missing":
        await self.revoke(binding)
        with self.store.transaction() as db:
            db.execute(
                "UPDATE computer_provider_bindings SET active=0,status='deleted',cleanup_state=? WHERE id=?",
                (
                    "pending_disks" if profile.provider == "azure_vm" else "deleted",
                    binding["id"],
                ),
            )
        self.store.set_computer(binding["bot_id"], binding["session_id"], "closed")
        self.finish(
            op,
            detail="Managed compute deletion confirmed. Retained VM disks and network inventory require explicit cleanup."
            if profile.provider == "azure_vm"
            else "Managed compute deletion confirmed.",
        )
    elif report.get("provisioning") in {"failed", "canceled", "cancelled"}:
        self.finish(
            op,
            "failed",
            "Azure reported a failed operation. The resource and cleanup inventory remain tracked.",
            "azure_operation_failed",
        )
    else:
        self.update(op, "polling")
    return


async def connecting(self: CloudComputers, op, binding, operation, driver, profile):
    conn = self.agents.connections.get(binding["id"])
    if not conn or not conn.ready or not conn.lease_ack:
        self.update(
            op,
            detail="Waiting for the enrolled host's control and data connections.",
        )
        return
    if binding["status"] == "quarantined":
        return self.finish(
            op,
            "failed",
            "Stop and inspect this host before starting a new task.",
            "recovery_required",
        )
    self.update(op, "ensuring")
    with self.store.transaction() as db:
        db.execute(
            "UPDATE computer_provider_bindings SET status='ensuring' WHERE id=?",
            (binding["id"],),
        )
    await self.agents.call(
        binding,
        "sandbox.ensure",
        self.host_profile(binding),
        op["operation_id"] + "-ensure",
    )
    self.update(op, "verifying")
    return


async def verifying(self: CloudComputers, op, binding, operation, driver, profile):
    report = await self.agents.call(binding, "sandbox.inspect", {}, op["operation_id"] + "-inspect")
    if report.get("lifecycle") == "running" and report.get("compatible"):
        with self.store.transaction() as db:
            db.execute(
                "UPDATE computer_provider_bindings SET status='ready' WHERE id=?",
                (binding["id"],),
            )
        self.store.set_computer(binding["bot_id"], binding["session_id"], "running")
        self.finish(
            op,
            detail="Computer ready. Resume the agent explicitly before sending a new task.",
        )
    else:
        self.update(op, "verifying")
    return


async def resetting(self: CloudComputers, op, binding, operation, driver, profile):
    self.quarantine(binding["id"], "Reset was interrupted; retirement was not confirmed")
    self.finish(
        op,
        "outcome_unknown",
        "Reset was interrupted. Stop and inspect the host; the action will not repeat.",
        "reset_interrupted",
    )
