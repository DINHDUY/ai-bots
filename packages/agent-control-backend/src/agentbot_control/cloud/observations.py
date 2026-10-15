from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from agentbot_control.cloud import later
from agentbot_control.event_store import identifier, packed, stamp
from agentbot_control.providers.azure import CloudError

if TYPE_CHECKING:
    from agentbot_control.cloud import CloudComputers


def update(self: CloudComputers, op, phase=None, **values):
    values.update(updated_at=stamp(), next_poll=later(values.pop("delay", 5)))
    if phase:
        values["phase"] = phase
    with self.store.transaction() as db:
        db.execute(
            "UPDATE cloud_operation_state SET "
            + ",".join(k + "=?" for k in values)
            + " WHERE operation_id=?",
            (*values.values(), op["operation_id"]),
        )


def finish(self: CloudComputers, op, phase="completed", detail=None, code=None):
    self.update(op, phase, detail=detail, error_code=code)
    result = self.progress(self.operation(op["operation_id"]))
    with self.store.transaction() as db:
        db.execute(
            "UPDATE lifecycle_operations SET status=?,result=? WHERE id=?",
            (phase, packed(result), op["operation_id"]),
        )
        if (
            op.get("bot_id")
            and db.execute("SELECT 1 FROM bot_streams WHERE bot_id=?", (op["bot_id"],)).fetchone()
        ):
            self.store._event(db, op["bot_id"], "lifecycle." + phase, result)
        elif op.get("workspace_id"):
            from agentbot_control.shared_computers.resolution import emit_workspace

            emit_workspace(self.store, db, op["workspace_id"], "lifecycle." + phase, result)


def submitted(self: CloudComputers, op, response):
    response = response or {}
    continuation = response.get("continuation")
    self.update(
        op,
        "polling",
        correlation_id=response.get("correlation_id"),
        continuation_sealed=self.policies.seal({"token": continuation}) if continuation else None,
    )


async def pause(self: CloudComputers, binding):
    if binding.get("workspace_id") and not binding.get("bot_id"):
        from agentbot_control.shared_computers.cloud import pause_shared

        return await pause_shared(self, binding)
    bot_id, sid = binding["bot_id"], binding["session_id"]
    with self.store.transaction() as db:
        db.execute(
            "INSERT INTO computer_control(session_id,paused,fence) VALUES (?,1,1) ON CONFLICT(session_id) DO UPDATE SET paused=1,fence=fence+1",
            (sid,),
        )
    run = self.store.active(bot_id)
    if run:
        self.stop(bot_id, run["id"], identifier("cloud_stop"))
        task = self.tasks.get(run["id"])
        if task:
            try:
                await asyncio.wait_for(asyncio.shield(task), 30)
            except (Exception, asyncio.CancelledError):
                if not task.done():
                    self.quarantine(binding["id"], "Run termination is not yet confirmed")
    lease = self.control.state(bot_id)["lease"]
    if lease:
        try:
            await self.control.release_by_id(lease["id"])
        except Exception:
            self.control.retire(bot_id, sid)


def verify_resource(self: CloudComputers, binding, report):
    p = self.profile_for(binding)
    if report["power"] == "missing":
        raise CloudError("azure_not_found", "The approved compute resource does not exist.")
    self.verify_managed_identity(binding, report)
    if str(report.get("region", "")).lower() != p.region or report.get("size") not in p.sizes:
        raise CloudError(
            "resource_policy_mismatch",
            "Azure location or machine size does not match the approved profile.",
        )
    owner = binding["owner_id"]
    with self.store.transaction() as db:
        account = db.execute("SELECT username FROM users WHERE id=?", (owner,)).fetchone()
    if p.provider == "azure_ml_compute_instance" and p.assigned_users.get(
        report.get("owner_object_id")
    ) not in {owner, account[0] if account else None}:
        raise CloudError(
            "assigned_owner_mismatch",
            "The Azure ML assigned user is not mapped to this bot's owner.",
        )
    with self.store.transaction() as db:
        db.execute(
            "UPDATE computer_provider_bindings SET verified_owner=?,observed_state=?,observed_at=? WHERE id=?",
            (owner, report["power"], stamp(), binding["id"]),
        )


def verify_managed_identity(self: CloudComputers, binding, report):
    if (
        binding["ownership"] == "managed"
        and report.get("tags", {}).get("agentcontrol-binding") != binding["id"]
    ):
        raise CloudError(
            "resource_identity_changed",
            "The managed resource no longer matches its recorded creation. It will not be modified.",
        )


async def observe_binding(self: CloudComputers, binding):
    try:
        report = await self.driver(binding).inspect(binding["resource_id"])
        if report["power"] != "missing":
            self.verify_resource(binding, report)
        with self.store.transaction() as db:
            db.execute(
                "UPDATE computer_provider_bindings SET observed_state=?,observed_at=? WHERE id=?",
                (report["power"], stamp(), binding["id"]),
            )
        return report
    except CloudError as exc:
        with self.store.transaction() as db:
            db.execute(
                "UPDATE computer_provider_bindings SET observed_state='unknown',observed_at=? WHERE id=?",
                (stamp(), binding["id"]),
            )
        if exc.code in {
            "resource_identity_changed",
            "resource_policy_mismatch",
            "assigned_owner_mismatch",
            "wrong_compute_type",
        }:
            self.quarantine(binding["id"], str(exc))
        raise


async def revoke(self: CloudComputers, binding):
    with self.store.transaction() as db:
        db.execute(
            "UPDATE cloud_machine_credentials SET revoked_at=? WHERE binding_id=? AND revoked_at IS NULL",
            (stamp(), binding["id"]),
        )
        db.execute(
            "UPDATE cloud_enrollments SET consumed_at=? WHERE binding_id=? AND consumed_at IS NULL",
            (stamp(), binding["id"]),
        )
    conn = self.agents.connections.get(binding["id"])
    if conn:
        await conn.disconnect()
