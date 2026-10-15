from __future__ import annotations

from typing import TYPE_CHECKING

from agentbot_control.cloud import TERMINAL, later
from agentbot_control.event_store import stamp
from agentbot_control.schemas import Conflict

if TYPE_CHECKING:
    from agentbot_control.cloud import CloudComputers


def operation(self: CloudComputers, operation_id):
    with self.store.transaction() as db:
        row = db.execute(
            "SELECT * FROM cloud_operation_state WHERE operation_id=?",
            (operation_id,),
        ).fetchone()
    return dict(row) if row else None


def progress(self: CloudComputers, op):
    return {
        "operation_id": op["operation_id"],
        "operation": op["operation"],
        "status": op["phase"] if op["phase"] in TERMINAL else "accepted",
        "phase": op["phase"],
        "detail": op["detail"],
        "error_code": op["error_code"],
        "deadline": op["deadline"],
        "updated_at": op["updated_at"],
    }


def active_operation(self: CloudComputers, binding_id):
    with self.store.transaction() as db:
        row = db.execute(
            "SELECT * FROM cloud_operation_state WHERE binding_id=? ORDER BY created_at DESC LIMIT 1",
            (binding_id,),
        ).fetchone()
    return dict(row) if row else None


def details(self: CloudComputers, binding):
    profile = self.profile_for(binding)
    return {
        k: binding[k]
        for k in (
            "id",
            "resource_id",
            "ownership",
            "provider",
            "generation",
            "status",
            "observed_state",
            "observed_at",
            "cleanup_state",
        )
    } | {
        "region": profile.region,
        "size": profile.default_size,
        "storage_policy": profile.storage_policy,
        "storage_ref": binding["storage_ref"],
        "idle_policy": profile.idle_policy,
    }


def actions(self: CloudComputers, user, bot_id):
    binding = self.binding(bot_id=bot_id)
    profile = (
        self.profile_for(binding)
        if binding
        else self.profiles.get(self.config(bot_id)["profile_id"])
    )
    if not profile or not self.can_manage(user, bot_id, profile):
        return []
    if not binding:
        return (
            ["create"]
            if self.config(bot_id)["ownership"] == "managed"
            and "create" in profile.allowed_operations
            else []
        )
    op = self.active_operation(binding["id"])
    if op and op["phase"] not in TERMINAL:
        return []
    allowed = profile.allowed_operations
    result = [a for a in ("start", "stop", "reset", "close") if a in allowed]
    if self.report(bot_id)["compatible"]:
        result = [a for a in result if a != "start"] + ["keep-warm"]
    if binding["observed_state"] in {"stopped", "deallocated", "missing"}:
        result = [a for a in result if a not in {"stop", "reset"}]
    if (
        binding["ownership"] == "managed"
        and "delete" in allowed
        and self.can_manage(user, bot_id, profile, administrator=True)
    ):
        result.append("delete-managed")
    return result


def report(self: CloudComputers, bot_id):
    config, binding = self.config(bot_id), self.binding(bot_id=bot_id)
    profile = self.profile_for(binding) if binding else self.profiles.get(config["profile_id"])
    conn = self.agents.connections.get(binding["id"]) if binding else None
    operation = self.active_operation(binding["id"]) if binding else None
    ready = bool(
        binding
        and binding["status"] == "ready"
        and binding["observed_state"] == "running"
        and binding["observed_at"]
        and binding["observed_at"] > later(-90)
        and conn
        and conn.ready
        and self.agents.credential(conn.token)
    )
    if operation and operation["phase"] not in TERMINAL:
        ready = False
    services = dict(conn.hello.services) if ready else {}
    compatible = ready and all(
        services.get(k) for k in ("browser", "desktop", "files", "terminal", "input", "revisions")
    )
    return {
        "provider": config["provider"],
        "display_name": (
            "Azure ML" if config["provider"] == "azure_ml_compute_instance" else "Azure VM"
        )
        + (" · " + binding["resource_id"].rsplit("/", 1)[1] if binding else ""),
        "lifecycle": "running"
        if compatible
        else "stopped"
        if binding and binding["observed_state"] in {"stopped", "deallocated"}
        else "unknown"
        if binding
        else "missing",
        "power_state": binding["observed_state"] if binding else "unattached",
        "connectivity": "ready"
        if compatible
        else "needs_attention"
        if binding and binding["status"] == "quarantined"
        else "connecting"
        if binding and binding["observed_state"] == "running"
        else "offline",
        "services": services,
        "compatible": compatible,
        "health": "healthy" if compatible else "unavailable",
        "observed_at": stamp(),
        "power_observed_at": binding["observed_at"] if binding else None,
        "operation": self.progress(operation) if operation else None,
        "retention_policy": profile.idle_policy if profile else "manual",
        "computer": self.store.computer(bot_id),
        "capabilities": {"capture": compatible, "health": True},
    }


def require_run(self: CloudComputers, bot, user_id):
    if self.selected(bot.id) and self.store.health.snapshot().get("cloud_reconciliation") in {
        "stopped",
        "stalled",
    }:
        raise Conflict("Cloud reconciliation is unavailable", code="worker_unavailable")
    if not self.selected(bot.id):
        return
    if self.config(bot.id)["provider"] == "azure_ml_compute_instance" and user_id != bot.owner_id:
        raise Conflict("Azure ML Compute Instances are restricted to their mapped owner.")
    if not self.report(bot.id)["compatible"]:
        raise Conflict(
            "Cloud computer is not ready. Attach or explicitly start it, wait for the host connection, then send the task again."
        )


def quarantine(self: CloudComputers, binding_id, reason):
    binding = self.binding(binding_id=binding_id)
    if not binding or not binding["active"]:
        return
    with self.store.transaction() as db:
        db.execute(
            "UPDATE computer_provider_bindings SET status='quarantined',updated_at=? WHERE id=?",
            (stamp(), binding_id),
        )
        if binding["session_id"]:
            db.execute(
                "INSERT INTO computer_control(session_id,paused,fence) VALUES (?,1,1) ON CONFLICT(session_id) DO UPDATE SET paused=1,fence=fence+1",
                (binding["session_id"],),
            )
        if (
            binding.get("bot_id")
            and db.execute(
                "SELECT 1 FROM bot_streams WHERE bot_id=?", (binding["bot_id"],)
            ).fetchone()
        ):
            self.store._event(
                db,
                binding["bot_id"],
                "computer.recovery_required",
                {"detail": reason},
            )
        elif binding.get("workspace_id"):
            from agentbot_control.shared_computers.resolution import emit_workspace

            emit_workspace(
                self.store,
                db,
                binding["workspace_id"],
                "computer.recovery_required",
                {"detail": reason},
            )


def host_rebooted(self: CloudComputers, binding):
    from agentbot_control.shared_computers.resolution import session_busy_store

    busy = (
        session_busy_store(self.store, binding["session_id"])
        if not binding.get("bot_id")
        else self.store.active(binding["bot_id"])
    )
    if busy or binding["status"] == "ensuring":
        self.quarantine(
            binding["id"],
            "Host restarted with an unconfirmed action. Stop and inspect it before a new task.",
        )


def host_profile(self: CloudComputers, binding):
    p = self.profile_for(binding)
    return {
        "image": p.image,
        "workspace_root": p.workspace_root,
        "storage_ref": binding["storage_ref"],
        "storage_policy": p.storage_policy,
        "memory_mb": p.memory_mb,
        "cpu_count": p.cpu_count,
        "session_id": binding["session_id"],
        "generation": binding["generation"],
        "bot_id": binding["bot_id"],
        "resource_id": binding["resource_id"],
    }
