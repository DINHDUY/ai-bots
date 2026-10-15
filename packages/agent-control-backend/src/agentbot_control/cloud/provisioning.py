from __future__ import annotations

import json
import secrets
from types import SimpleNamespace
from typing import TYPE_CHECKING

from agentbot_control.cloud import later
from agentbot_control.event_store import identifier, packed, stamp
from agentbot_control.providers.azure import CloudError
from agentbot_control.providers.bootstrap import script
from agentbot_control.repositories import admission

if TYPE_CHECKING:
    from agentbot_control.cloud import CloudComputers


async def reserved(self: CloudComputers, op, binding, operation, driver, profile):
    with self.store.transaction() as db:
        row = db.execute("SELECT id,username FROM users WHERE id=?", (op["actor_id"],)).fetchone()
    if not row or not self.can_manage(
        SimpleNamespace(**dict(row)),
        op["bot_id"],
        profile,
        administrator=operation == "delete-managed",
        workspace_id=op.get("workspace_id"),
    ):
        return self.finish(
            op,
            "failed",
            "Compute management permission was revoked.",
            "permission_revoked",
        )
    if operation == "keep-warm":
        with self.store.transaction() as db:
            db.execute(
                "INSERT INTO computer_retention(session_id,keep_warm_until) VALUES (?,?) ON CONFLICT(session_id) DO UPDATE SET keep_warm_until=excluded.keep_warm_until,warned=0",
                (
                    binding["session_id"],
                    later(json.loads(op["inventory"])["minutes"] * 60),
                ),
            )
        return self.finish(op)
    await self.pause(binding)
    if operation == "close":
        confirmed = False
        try:
            await self.agents.call(binding, "sandbox.retire", {}, op["operation_id"])
            confirmed = True
        except Exception:
            pass
        await self.revoke(binding)
        with self.store.transaction() as db:
            db.execute(
                "UPDATE computer_provider_bindings SET active=0,status='retired',cleanup_state=? WHERE id=?",
                (
                    "retained" if confirmed and binding["ownership"] == "attached" else "pending",
                    binding["id"],
                ),
            )
        self.store.set_computer(binding["bot_id"], binding["session_id"], "closed")
        return self.finish(
            op,
            detail="Binding retired. Workspace data and the Azure host are retained."
            + (
                " Host cleanup remains tracked."
                if not confirmed or binding["ownership"] == "managed"
                else ""
            ),
        )
    report = await self.observe_binding(binding)
    if operation == "attach":
        self.verify_resource(binding, report)
        if report["power"] != "running":
            self.store.set_computer(binding["bot_id"], binding["session_id"], "hibernated")
            return self.finish(
                op,
                detail="Attached. Start the computer explicitly and enroll its host service.",
            )
        self.update(
            op,
            "connecting",
            detail="Resource verified. Enroll the host service to connect the sandbox.",
        )
        return
    if operation == "create":
        if report["power"] != "missing":
            return self.finish(
                op,
                "failed",
                "Reserved resource name already exists. It will not be modified.",
                "resource_collision",
            )
        inventory = driver.inventory(binding["resource_id"])
        for resource_id, kind in inventory:
            if await driver.inventory_exists(resource_id, kind):
                return self.finish(
                    op,
                    "failed",
                    "A reserved dependency name already exists. It will not be modified.",
                    "resource_collision",
                )
        with self.store.transaction() as db:
            for resource_id, kind in inventory:
                db.execute(
                    "INSERT INTO cloud_resource_inventory(binding_id,resource_id,kind,operation_id) VALUES (?,?,?,?)",
                    (binding["id"], resource_id, kind, op["operation_id"]),
                )
        self.update(op, "bootstrap")
        return
    if operation == "reset":
        connection = self.agents.connections.get(binding["id"])
        if binding["status"] != "ready" or not connection or not connection.ready:
            raise CloudError(
                "bridge_unavailable",
                "Connect the sandbox before resetting it.",
            )
        self.update(op, "resetting")  # never repeat a retirement after a lost result
        await self.agents.call(binding, "sandbox.retire", {}, op["operation_id"] + "-retire")
        self.store.set_computer(binding["bot_id"], binding["session_id"], "closed")
        sid, now = identifier("computer"), stamp()
        with self.store.transaction() as db:
            admission.require_computer(
                db, binding["bot_id"], self.store.admission_limits, owner_id=binding["owner_id"]
            )
            column, owner = (
                ("bot_id", binding["bot_id"])
                if binding["bot_id"]
                else ("workspace_id", binding["workspace_id"])
            )
            db.execute(
                f"INSERT INTO computer_sessions (id,{column},generation,status,created_at,updated_at) VALUES (?,?,?,'provisioning',?,?)",
                (sid, owner, binding["generation"] + 1, now, now),
            )
            db.execute(
                "UPDATE computer_provider_bindings SET session_id=?,generation=generation+1,status='registered' WHERE id=?",
                (sid, binding["id"]),
            )
        self.clients.pop(binding["id"], None)
        self.update(
            op,
            "connecting",
            detail="Creating a fresh sandbox generation; earlier workspace data is retained.",
        )
        return
    if operation == "start" and report["power"] == "running":
        self.update(op, "connecting")
        return
    if operation == "stop" and report["power"] in {
        "stopped",
        "deallocated",
    }:
        self.update(op, "polling")
        return
    self.update(op, "submitting", submitted_at=stamp())
    response = await driver.submit(
        "delete" if operation == "delete-managed" else operation,
        binding["resource_id"],
        op["operation_id"],
    )
    self.submitted(op, response)
    return


async def bootstrap(self: CloudComputers, op, binding, operation, driver, profile):
    with self.store.transaction() as db:
        account = db.execute(
            "SELECT username FROM users WHERE id=?", (binding["owner_id"],)
        ).fetchone()
    owner = next(
        (
            key
            for key, value in profile.assigned_users.items()
            if value in {binding["owner_id"], account[0] if account else None}
        ),
        None,
    )
    if profile.provider == "azure_ml_compute_instance" and not owner:
        raise CloudError(
            "assigned_owner_mismatch",
            "Configure an explicit Entra assigned-user mapping for this owner.",
        )
    host_key = secrets.token_hex(32)
    grant = self.agents.enrollment(binding, host_key)
    secret_name = "agentcontrol-" + op["operation_id"].replace("_", "-")
    await driver.save_enrollment(
        secret_name,
        packed(
            {
                "code": grant["code"],
                "binding_id": binding["id"],
                "host_key": host_key,
            }
        ),
    )
    with self.store.transaction() as db:
        db.execute(
            "UPDATE computer_provider_bindings SET verified_owner=? WHERE id=?",
            (binding["owner_id"], binding["id"]),
        )
    self.update(op, "submitting", submitted_at=stamp())
    response = await driver.submit(
        "create",
        binding["resource_id"],
        op["operation_id"],
        tags={
            "agentcontrol-deployment": self.store.deployment,
            "agentcontrol-binding": binding["id"],
            "agentcontrol-operation": op["operation_id"],
        },
        bootstrap=script(profile, secret_name),
        owner_object_id=owner,
    )
    self.submitted(op, response)
    return
