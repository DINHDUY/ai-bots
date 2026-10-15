"""Workspace-owned Azure computer. Per-bot cloud behavior stays on the bot subject."""

from __future__ import annotations

import json
import secrets

from agentbot_control.common import fingerprint, identifier, packed, stamp
from agentbot_control.repositories import admission
from agentbot_control.schemas import Conflict
from agentbot_control.shared_computers.lifecycle import WorkspaceLifecycle
from agentbot_control.shared_computers.resolution import (
    active_runs,
    emit_workspace,
    open_computer,
    settings_row,
)


def binding_report(cloud, binding):
    conn = cloud.agents.connections.get(binding["id"]) if binding else None
    operation = cloud.active_operation(binding["id"]) if binding else None
    from agentbot_control.cloud import TERMINAL, later

    ready = bool(
        binding
        and binding["status"] == "ready"
        and binding["observed_state"] == "running"
        and binding["observed_at"]
        and binding["observed_at"] > later(-90)
        and conn
        and conn.ready
        and cloud.agents.credential(conn.token)
    )
    if operation and operation["phase"] not in TERMINAL:
        ready = False
    services = dict(conn.hello.services) if ready else {}
    compatible = ready and all(
        services.get(key)
        for key in ("browser", "desktop", "files", "terminal", "input", "revisions")
    )
    provider = binding["provider"] if binding else "docker"
    return {
        "provider": provider,
        "display_name": ("Azure ML" if provider == "azure_ml_compute_instance" else "Azure VM"),
        "lifecycle": "running" if compatible else "unknown" if binding else "missing",
        "services": services,
        "compatible": compatible,
        "health": "healthy" if compatible else "unavailable",
        "observed_at": stamp(),
        "operation": cloud.progress(operation) if operation else None,
        "capabilities": {"capture": compatible, "health": True},
    }


async def pause_shared(cloud, binding):
    sid = binding["session_id"]

    def mark():
        with cloud.store.transaction() as db:
            db.execute(
                "INSERT INTO computer_control(session_id,paused,fence) VALUES (?,1,1) "
                "ON CONFLICT(session_id) DO UPDATE SET paused=1,fence=fence+1",
                (sid,),
            )
            return active_runs(db, sid)

    runs = await cloud.store.offload(mark)
    for run in runs:
        cloud.stop(run["bot_id"], run["id"], identifier("cloud_stop"))
        task = cloud.tasks.get(run["id"])
        if task:
            try:
                import asyncio

                await asyncio.wait_for(asyncio.shield(task), 30)
            except (Exception, asyncio.CancelledError):
                if not task.done():
                    cloud.quarantine(binding["id"], "Run termination is not yet confirmed")

    def lease():
        with cloud.store.transaction() as db:
            row = db.execute(
                "SELECT id FROM control_leases WHERE session_id=? AND status IN ('active','releasing')",
                (sid,),
            ).fetchone()
        return row[0] if row else None

    lease_id = await cloud.store.offload(lease)
    if lease_id:
        try:
            await cloud.control.release_by_id(lease_id)
        except Exception:
            cloud.control.retire("", sid)


class SharedCloud:
    def __init__(self, store, cloud):
        self.store = store
        self.cloud = cloud

    async def command(self, workspace_id, user, command: WorkspaceLifecycle):
        if command.operation not in {
            "attach",
            "create",
            "start",
            "stop",
            "keep-warm",
            "close",
            "delete-managed",
            "reset",
        }:
            raise Conflict("This lifecycle action is not available for the shared cloud computer.")
        digest = fingerprint(
            {
                "operation": command.operation,
                "generation": command.generation,
                "minutes": command.minutes,
                "resource_id": command.resource_id,
                "expected_revision": command.expected_revision,
            }
        )
        previous = self._receipt(workspace_id, command.request_id, digest)
        if previous:
            return previous
        settings = self._settings(workspace_id)
        profile = self.cloud.profiles.get(settings["profile_id"])
        if not profile or profile.provider != settings["provider"]:
            raise Conflict("The configured compute profile is unavailable.")
        self.cloud.require_manage(
            user,
            None,
            profile,
            workspace_id=workspace_id,
            administrator=command.operation == "delete-managed",
        )
        return await self._reserve(workspace_id, user, command, settings, profile, digest)

    def _open_computer(self, workspace_id):
        with self.store.transaction() as db:
            return open_computer(db, workspace_id)

    def _settings(self, workspace_id):
        with self.store.transaction() as db:
            return settings_row(db, workspace_id)

    def _receipt(self, workspace_id, request_id, digest):
        with self.store.transaction() as db:
            old = db.execute(
                "SELECT response, fingerprint FROM workspace_computer_receipts WHERE workspace_id=? AND request_id=?",
                (workspace_id, request_id),
            ).fetchone()
        if not old:
            return None
        if old["fingerprint"] != digest:
            raise Conflict("Request ID already used with different arguments.")
        return json.loads(old["response"])

    async def _reserve(self, workspace_id, user, command, settings, profile, digest):
        computer = self._open_computer(workspace_id)
        if (computer["generation"] if computer else 0) != command.generation:
            raise Conflict("Computer generation changed.")
        binding = self.cloud.binding(workspace_id=workspace_id)
        operation = command.operation
        if operation in {"attach", "create"}:
            if binding or (computer and computer["status"] != "closed"):
                raise Conflict("Close the current computer first.")
            resource_id = self._resource(profile, command, settings)
            sid, bid, now = identifier("computer"), identifier("cloud"), stamp()
            generation = command.generation + 1
            self._insert(
                workspace_id,
                user,
                profile,
                settings,
                command,
                resource_id,
                sid,
                bid,
                generation,
                now,
                digest,
            )
            binding = {"id": bid, "session_id": sid, "resource_id": resource_id}
        elif not binding:
            raise Conflict("No cloud computer is attached.")
        elif self._busy(binding["session_id"]) and operation != "keep-warm":
            raise Conflict(
                "A bot is using the shared computer. Wait for it to finish.", code="computer_busy"
            )
        oid, now = identifier("cloudop"), stamp()
        if operation not in {"attach", "create"}:
            self._operation(workspace_id, user, binding, operation, command, digest, oid, now)
        return self.cloud.progress(
            self.cloud.operation(
                oid
                if operation not in {"attach", "create"}
                else self._last_operation(binding["id"])
            )
        )

    def _resource(self, profile, command, settings):
        if command.operation == "attach":
            if (
                command.expected_revision != settings["revision"]
                or settings["ownership"] != "attached"
            ):
                raise Conflict(
                    "Computer configuration changed or is not configured for attachment."
                )
            try:
                return profile.attached_resource(command.resource_id)
            except ValueError as exc:
                raise Conflict(str(exc)) from exc
        if settings["ownership"] != "managed":
            raise Conflict("Select managed ownership before creating a cloud machine.")
        prefix = f"/subscriptions/{profile.subscription_id}/resourceGroups/{profile.resource_group}/providers/"
        prefix += (
            f"Microsoft.MachineLearningServices/workspaces/{profile.ml_workspace}/computes/"
            if profile.provider == "azure_ml_compute_instance"
            else "Microsoft.Compute/virtualMachines/"
        )
        return profile.resource(prefix + "ac-" + secrets.token_hex(8))

    def _insert(
        self,
        workspace_id,
        user,
        profile,
        settings,
        command,
        resource_id,
        sid,
        bid,
        generation,
        now,
        digest,
    ):
        with self.store.transaction() as db:
            owner = db.execute(
                "SELECT owner_id FROM workspaces WHERE id=?", (workspace_id,)
            ).fetchone()[0]
            count = db.execute(
                "SELECT COUNT(*) FROM computer_provider_bindings WHERE profile_id=? AND ownership='managed' AND cleanup_state!='deleted'",
                (profile.id,),
            ).fetchone()[0]
            if command.operation == "create" and count >= profile.max_hosts:
                raise Conflict(
                    "Profile machine limit reached, including retained cleanup inventory."
                )
            if db.execute(
                "SELECT 1 FROM computer_provider_bindings WHERE resource_id=? COLLATE NOCASE AND (active=1 OR cleanup_state IN ('pending','stopping','needs_attention'))",
                (resource_id,),
            ).fetchone():
                raise Conflict("This Azure resource is already assigned or has unresolved cleanup.")
            admission.require_computer(db, None, self.store.admission_limits, owner_id=owner)
            db.execute(
                "INSERT INTO computer_sessions (id,workspace_id,generation,status,created_at,updated_at) VALUES (?,?,?,'provisioning',?,?)",
                (sid, workspace_id, generation, now, now),
            )
            db.execute(
                "INSERT INTO computer_provider_bindings("
                "id,bot_id,owner_id,session_id,generation,provider,profile_id,profile_snapshot,resource_id,ownership,storage_ref,workspace_id,created_at,updated_at"
                ") VALUES (?,NULL,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    bid,
                    owner,
                    sid,
                    generation,
                    profile.provider,
                    profile.id,
                    profile.model_dump_json(),
                    resource_id,
                    settings["ownership"],
                    bid,
                    workspace_id,
                    now,
                    now,
                ),
            )
            self._operation_db(
                db,
                workspace_id,
                user,
                {"id": bid, "session_id": sid, "resource_id": resource_id},
                command.operation,
                command,
                digest,
                identifier("cloudop"),
                now,
            )

    def _operation(self, workspace_id, user, binding, operation, command, digest, oid, now):
        with self.store.transaction() as db:
            self._operation_db(
                db, workspace_id, user, binding, operation, command, digest, oid, now
            )

    def _operation_db(self, db, workspace_id, user, binding, operation, command, digest, oid, now):
        db.execute(
            "INSERT INTO lifecycle_operations(id,workspace_id,request_id,fingerprint,session_id,operation,status,created_at) "
            "VALUES (?,?,?,?,?,?,'running',?)",
            (oid, workspace_id, command.request_id, digest, binding["session_id"], operation, now),
        )
        db.execute(
            "INSERT INTO cloud_operation_state("
            "operation_id,binding_id,bot_id,actor_id,operation,phase,target_resource_id,deadline,next_poll,inventory,workspace_id,created_at,updated_at"
            ") VALUES (?,?,NULL,?,?,'reserved',?,?,?,?,?,?,?)",
            (
                oid,
                binding["id"],
                user.id,
                operation,
                binding["resource_id"],
                _deadline(self.cloud, binding),
                now,
                packed({"minutes": command.minutes}),
                workspace_id,
                now,
                now,
            ),
        )
        response = {"operation_id": oid, "status": "accepted", "operation": operation}
        db.execute(
            "INSERT INTO workspace_computer_receipts VALUES (?,?,?,?)",
            (workspace_id, command.request_id, digest, json.dumps(response)),
        )
        emit_workspace(
            self.store,
            db,
            workspace_id,
            "lifecycle.started",
            {"operation_id": oid, "operation": operation, "status": "accepted"},
        )

    def _last_operation(self, binding_id):
        op = self.cloud.active_operation(binding_id)
        return op["operation_id"] if op else None

    def _busy(self, sid) -> bool:
        from agentbot_control.shared_computers.resolution import session_busy_store

        return session_busy_store(self.store, sid)


def _deadline(cloud, binding):
    from agentbot_control.cloud import later

    profile = cloud.profile_for(binding) if binding.get("profile_snapshot") else None
    seconds = profile.operation_timeout_seconds if profile else 900
    return later(seconds)
