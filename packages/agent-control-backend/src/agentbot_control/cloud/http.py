from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse

from agentbot_control.cloud import AttachCloud, ComputeGrant, EnrollHost
from agentbot_control.event_store import stamp
from agentbot_control.providers.azure import CloudError
from agentbot_control.repositories.workspace_cleanup import recovery_binding
from agentbot_control.schemas import Command, Conflict
from agentbot_control.transport import body

if TYPE_CHECKING:
    from agentbot_control.cloud import CloudComputers


def routes(self: CloudComputers, app):
    self.agents.routes(app)

    @app.get("/api/workspaces/{workspace_id}/compute-profiles")
    async def profiles(workspace_id: str, request: Request):
        user = self.workspaces.user(request)
        role = self.workspaces.role(user.id, workspace_id)
        return {
            "profiles": [
                p.public()
                for p in self.profiles.values()
                if p.workspace_id == workspace_id
                and role in {"owner", "operator"}
                and (
                    not p.managers
                    or {user.id, user.username}.intersection(p.managers + p.administrators)
                )
            ]
        }

    @app.post("/api/bots/{bot_id}/computer/attach")
    async def attach(bot_id: str, request: Request):
        user, bot = self.actor(request, bot_id)
        command = await body(request, AttachCloud)
        result = await self.admit(user, bot, "attach", command, command.resource_id)
        return JSONResponse(result, status_code=202 if result["status"] == "accepted" else 200)

    @app.get("/api/bots/{bot_id}/lifecycle/operations/{operation_id}")
    async def progress(bot_id: str, operation_id: str, request: Request):
        self.actor(request, bot_id)
        op = self.operation(operation_id)
        if not op or op["bot_id"] != bot_id:
            raise HTTPException(404, "Operation not found")
        return self.progress(op)

    @app.post("/api/bots/{bot_id}/computer/enrollment")
    async def enrollment(bot_id: str, request: Request):
        user, _ = self.actor(request, bot_id)
        binding = self.binding(bot_id=bot_id)
        if not binding or not binding["verified_owner"]:
            raise Conflict(
                "Wait for Azure resource and assigned-owner verification before enrollment."
            )
        self.require_manage(user, bot_id, self.profile_for(binding))
        command = await body(request, EnrollHost)
        await self.revoke(binding)
        return {
            "binding_id": binding["id"],
            **self.agents.enrollment(binding, command.host_key),
        }

    @app.post("/api/bots/{bot_id}/computer/revoke")
    async def revoke(bot_id: str, request: Request):
        user, _ = self.actor(request, bot_id)
        binding = self.binding(bot_id=bot_id)
        if not binding:
            raise Conflict("No attached computer")
        self.require_manage(user, bot_id, self.profile_for(binding))
        await body(request, Command)
        await self.pause(binding)
        await self.revoke(binding)
        self.quarantine(
            binding["id"],
            "Host access revoked; stop the computer before reconnecting",
        )
        return {"revoked": True}

    @app.post("/api/bots/{bot_id}/compute-grants")
    async def grant_compute(bot_id: str, request: Request):
        user, bot = self.actor(request, bot_id)
        if user.id != bot.owner_id:
            raise HTTPException(403, "Only the bot owner can grant compute management")
        command = await body(request, ComputeGrant)
        uid = self.workspaces.recipient(command.username)
        with self.store.transaction() as db:
            member = db.execute(
                "SELECT m.role FROM workspace_members m JOIN bot_streams b ON b.workspace_id=m.workspace_id WHERE b.bot_id=? AND m.user_id=?",
                (bot_id, uid),
            ).fetchone()
            if not member or member[0] not in {"owner", "operator"}:
                raise Conflict("Compute managers must be workspace operators or owners.")
            if command.enabled:
                db.execute(
                    "INSERT OR IGNORE INTO compute_management_grants VALUES (?,?)",
                    (bot_id, uid),
                )
            else:
                db.execute(
                    "DELETE FROM compute_management_grants WHERE bot_id=? AND user_id=?",
                    (bot_id, uid),
                )
            self.store._event(
                db,
                bot_id,
                "compute.grant_changed",
                {"user_id": uid, "can_manage_compute": command.enabled},
            )
        return {"user_id": uid, "can_manage_compute": command.enabled}

    @app.get("/api/workspaces/{workspace_id}/compute-inventory")
    async def inventory(workspace_id: str, request: Request):
        user = self.workspaces.user(request)
        deleted_owner = self.workspaces.recovery_owner(user.id, workspace_id)
        allowed = {
            p.id
            for p in self.profiles.values()
            if p.workspace_id == workspace_id
            and {user.id, user.username}.intersection(p.administrators)
        }
        with self.store.transaction() as db:
            rows = [
                dict(r)
                for r in db.execute("SELECT * FROM computer_provider_bindings")
                if r["profile_id"] in allowed
                or (
                    deleted_owner
                    and r["owner_id"] == user.id
                    and recovery_binding(db, r, workspace_id)
                )
            ]
            result = [
                {
                    **self.details(r),
                    "active": bool(r["active"]),
                    "resources": [
                        dict(v)
                        for v in db.execute(
                            "SELECT resource_id,kind,status FROM cloud_resource_inventory WHERE binding_id=?",
                            (r["id"],),
                        )
                    ],
                }
                for r in rows
            ]
        return {"computers": result}

    @app.post("/api/workspaces/{workspace_id}/compute-inventory/{binding_id}/reconcile")
    async def reconcile_inventory(workspace_id: str, binding_id: str, request: Request):
        user = self.workspaces.user(request)
        deleted_owner = self.workspaces.recovery_owner(user.id, workspace_id)
        binding = self.binding(binding_id=binding_id)
        profile = self.profile_for(binding) if binding else None
        if (
            not binding
            or not profile
            or profile.workspace_id != workspace_id
            or not (deleted_owner and binding["owner_id"] == user.id)
            and not {user.id, user.username}.intersection(profile.administrators)
        ):
            raise HTTPException(404, "Inventory not found")
        await body(request, Command)
        if binding["active"]:
            raise Conflict("Retire this binding before resolving its inventory.")
        driver = self.driver(binding)
        try:
            report = await driver.inspect(binding["resource_id"])
            if report["power"] in {"stopped", "deallocated"}:
                self.verify_managed_identity(binding, report)
                # A confirmed stopped host cannot still execute an old writer.
                with self.store.transaction() as db:
                    db.execute(
                        "UPDATE computer_provider_bindings SET cleanup_state='retained_stopped',observed_state=?,observed_at=? WHERE id=?",
                        (report["power"], stamp(), binding_id),
                    )
                return {
                    "binding_id": binding_id,
                    "cleanup_state": "retained_stopped",
                }
            if report["power"] != "missing":
                raise Conflict("The Azure host still exists; its inventory must remain tracked.")
            with self.store.transaction() as db:
                rows = [
                    dict(r)
                    for r in db.execute(
                        "SELECT * FROM cloud_resource_inventory WHERE binding_id=?",
                        (binding_id,),
                    )
                ]
            for resource in rows:
                if await driver.inventory_exists(resource["resource_id"], resource["kind"]):
                    raise Conflict(
                        "A recorded disk or NIC still exists. Complete its approved cleanup first."
                    )
        except CloudError as exc:
            raise Conflict(str(exc)) from exc
        with self.store.transaction() as db:
            db.execute(
                "UPDATE computer_provider_bindings SET cleanup_state='deleted',status='deleted',observed_state='missing',observed_at=? WHERE id=?",
                (stamp(), binding_id),
            )
            db.execute(
                "UPDATE cloud_resource_inventory SET status='deleted' WHERE binding_id=?",
                (binding_id,),
            )
        return {"binding_id": binding_id, "cleanup_state": "deleted"}
