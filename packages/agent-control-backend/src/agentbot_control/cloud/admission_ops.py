from __future__ import annotations

import secrets
from typing import TYPE_CHECKING

from agentbot_control.cloud import TERMINAL, later
from agentbot_control.event_store import fingerprint, identifier, packed, stamp
from agentbot_control.repositories import admission
from agentbot_control.schemas import Conflict

if TYPE_CHECKING:
    from agentbot_control.cloud import CloudComputers


async def admit(self: CloudComputers, user, bot, operation, command, resource_id=None):
    async with self.mutex(bot.id):
        reservation = None
        digest = fingerprint(
            {
                "operation": operation,
                **command.model_dump(),
                "resource_id": resource_id,
            }
        )
        with self.store.transaction() as db:
            old = db.execute(
                "SELECT * FROM cloud_operation_receipts WHERE bot_id=? AND request_id=?",
                (bot.id, command.request_id),
            ).fetchone()
        if old:
            if old["fingerprint"] != digest:
                raise Conflict("Request ID already used with different arguments.")
            return self.progress(self.operation(old["operation_id"]))
        binding = self.binding(bot_id=bot.id)
        profile = self.profile_for(binding) if binding else self.configured_profile(bot.id)
        self.require_manage(user, bot.id, profile, administrator=operation == "delete-managed")
        capability = "delete" if operation == "delete-managed" else operation
        if capability not in profile.allowed_operations and operation != "keep-warm":
            raise Conflict("This lifecycle action is disabled by the compute profile.")
        computer = self.store.computer(bot.id)
        if (computer["generation"] if computer else 0) != command.generation:
            raise Conflict("Computer generation changed.")
        if operation == "keep-warm":
            if (
                not binding
                or not self.report(bot.id)["compatible"]
                or command.minutes > profile.max_warm_minutes
            ):
                raise Conflict("Only a ready computer can stay warm, within the profile limit.")
        elif operation in {"attach", "create"}:
            if binding or (computer and computer["status"] != "closed"):
                raise Conflict("Close the current computer first.")
            config = self.config(bot.id)
            if operation == "attach" and (
                command.expected_revision != config["revision"] or config["ownership"] != "attached"
            ):
                raise Conflict(
                    "Computer configuration changed or is not configured for attachment."
                )
            if operation == "create" and config["ownership"] != "managed":
                raise Conflict("Select managed ownership before creating a cloud machine.")
            if operation == "attach":
                try:
                    resource_id = profile.attached_resource(resource_id)
                except ValueError as exc:
                    raise Conflict(str(exc)) from exc
            else:
                prefix = f"/subscriptions/{profile.subscription_id}/resourceGroups/{profile.resource_group}/providers/"
                prefix += (
                    f"Microsoft.MachineLearningServices/workspaces/{profile.ml_workspace}/computes/"
                    if profile.provider == "azure_ml_compute_instance"
                    else "Microsoft.Compute/virtualMachines/"
                )
                resource_id = profile.resource(prefix + "ac-" + secrets.token_hex(8))
            with self.store.transaction() as db:
                count = db.execute(
                    "SELECT COUNT(*) FROM computer_provider_bindings WHERE profile_id=? AND ownership='managed' AND cleanup_state!='deleted'",
                    (profile.id,),
                ).fetchone()[0]
                if operation == "create" and count >= profile.max_hosts:
                    raise Conflict(
                        "Profile machine limit reached, including retained cleanup inventory."
                    )
                if db.execute(
                    "SELECT 1 FROM computer_provider_bindings WHERE resource_id=? COLLATE NOCASE AND (active=1 OR cleanup_state IN ('pending','stopping','needs_attention'))",
                    (resource_id,),
                ).fetchone():
                    raise Conflict(
                        "This Azure resource is already assigned or has unresolved cleanup."
                    )
                sid, bid, now = identifier("computer"), identifier("cloud"), stamp()
                generation = command.generation + 1
                reservation = (
                    bid,
                    bot.id,
                    bot.owner_id,
                    sid,
                    generation,
                    profile.provider,
                    profile.id,
                    profile.model_dump_json(),
                    resource_id,
                    config["ownership"],
                    bid,
                    now,
                    now,
                )
            binding = {
                "id": bid,
                "session_id": sid,
                "resource_id": resource_id,
                "ownership": config["ownership"],
            }
        elif not binding:
            raise Conflict("No cloud computer is attached.")
        if operation == "delete-managed" and binding["ownership"] != "managed":
            raise Conflict("Attached Azure resources cannot be deleted by Agent Control.")
        active = self.active_operation(binding["id"])
        if active and active["phase"] not in TERMINAL:
            raise Conflict("A lifecycle operation is already in progress.")
        oid, now = identifier("cloudop"), stamp()
        with self.store.transaction() as db:
            if reservation:
                admission.require_computer(db, bot.id, self.store.admission_limits)
                db.execute(
                    "INSERT INTO computer_sessions (id,bot_id,generation,status,created_at,updated_at) VALUES (?,?,?,'provisioning',?,?)",
                    (sid, bot.id, generation, now, now),
                )
                db.execute(
                    "INSERT INTO computer_provider_bindings(id,bot_id,owner_id,session_id,generation,provider,profile_id,profile_snapshot,resource_id,ownership,storage_ref,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    reservation,
                )
            db.execute(
                "INSERT INTO lifecycle_operations(id,bot_id,request_id,fingerprint,session_id,operation,status,created_at) VALUES (?,?,?,?,?,?,'running',?)",
                (
                    oid,
                    bot.id,
                    command.request_id,
                    digest,
                    binding["session_id"],
                    operation,
                    now,
                ),
            )
            db.execute(
                "INSERT INTO cloud_operation_state(operation_id,binding_id,bot_id,actor_id,operation,phase,target_resource_id,deadline,next_poll,inventory,created_at,updated_at) VALUES (?,?,?,?,?,'reserved',?,?,?,?,?,?)",
                (
                    oid,
                    binding["id"],
                    bot.id,
                    user.id,
                    operation,
                    binding["resource_id"],
                    later(profile.operation_timeout_seconds),
                    now,
                    packed({"minutes": getattr(command, "minutes", 30)}),
                    now,
                    now,
                ),
            )
            db.execute(
                "INSERT INTO cloud_operation_receipts VALUES (?,?,?,?)",
                (bot.id, command.request_id, digest, oid),
            )
            self.store._event(
                db,
                bot.id,
                "lifecycle.started",
                {"operation_id": oid, "operation": operation, "status": "accepted"},
            )
        return self.progress(self.operation(oid))
