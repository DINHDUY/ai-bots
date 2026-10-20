from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import HTTPException

from agentbot_control.cloud import CLOUD
from agentbot_control.compute_profiles import ComputeProfile
from agentbot_control.providers.azure import AzureDriver
from agentbot_control.schemas import Conflict

if TYPE_CHECKING:
    from agentbot_control.cloud import CloudComputers


def config(self: CloudComputers, bot_id):
    with self.store.transaction() as db:
        row = db.execute("SELECT * FROM cloud_compute_config WHERE bot_id=?", (bot_id,)).fetchone()
    return (
        dict(row)
        if row
        else {
            "provider": "docker",
            "revision": 0,
            "profile_id": None,
            "ownership": "attached",
        }
    )


def selected(self: CloudComputers, bot_id):
    return self.config(bot_id)["provider"] in CLOUD


def binding(
    self: CloudComputers, *, bot_id=None, binding_id=None, session_id=None, workspace_id=None
):
    with self.store.transaction() as db:
        row = db.execute(
            "SELECT * FROM computer_provider_bindings WHERE (? IS NOT NULL AND id=?) OR (? IS NOT NULL AND bot_id=? AND active=1) OR (? IS NOT NULL AND session_id=?) OR (? IS NOT NULL AND workspace_id=? AND active=1) ORDER BY created_at DESC LIMIT 1",
            (
                binding_id,
                binding_id,
                bot_id,
                bot_id,
                session_id,
                session_id,
                workspace_id,
                workspace_id,
            ),
        ).fetchone()
    return dict(row) if row else None


def profile_for(self: CloudComputers, binding):
    return ComputeProfile.model_validate_json(binding["profile_snapshot"])


def driver(self: CloudComputers, binding):
    key = binding["id"]
    if key not in self.drivers:
        self.drivers[key] = AzureDriver(self.profile_for(binding))
    return self.drivers[key]


def actor(self: CloudComputers, request, bot_id):
    user = self.workspaces.user(request)
    bot = self.workspaces.bot(user.id, bot_id, "read")
    self.ensure(bot)
    return user, bot


def can_manage(
    self: CloudComputers, user, bot_id, profile=None, *, administrator=False, workspace_id=None
):
    if not bot_id and workspace_id:
        try:
            self.workspaces.role(user.id, workspace_id, owner=True)
        except HTTPException:
            return False
        identities = {user.id, getattr(user, "username", None)}
        if administrator:
            return bool(profile and identities.intersection(profile.administrators))
        return True
    try:
        bot = self.workspaces.bot(user.id, bot_id, "read")
    except HTTPException:
        return False
    identities = {user.id, user.username}
    if administrator:
        return bool(profile and identities.intersection(profile.administrators))
    if (
        profile
        and profile.managers
        and not identities.intersection(profile.managers + profile.administrators)
    ):
        return False
    if user.id == bot.owner_id or (profile and identities.intersection(profile.administrators)):
        return True
    with self.store.transaction() as db:
        return bool(
            db.execute(
                "SELECT 1 FROM compute_management_grants g JOIN bot_streams b ON b.bot_id=g.bot_id JOIN workspace_members m ON m.workspace_id=b.workspace_id AND m.user_id=g.user_id WHERE g.bot_id=? AND g.user_id=? AND m.role IN ('owner','operator')",
                (bot_id, user.id),
            ).fetchone()
        )


def require_manage(self: CloudComputers, user, bot_id, profile=None, **kwargs):
    if not self.can_manage(user, bot_id, profile, **kwargs):
        raise HTTPException(403, "Compute management permission is required.")


def configured_profile(self: CloudComputers, bot_id):
    config = self.config(bot_id)
    profile = self.profiles.get(config["profile_id"])
    if not profile or profile.provider != config["provider"]:
        raise Conflict(
            "The configured compute profile is unavailable. Ask the operator to restore it."
        )
    with self.store.transaction() as db:
        wid = db.execute(
            "SELECT workspace_id FROM bot_streams WHERE bot_id=?", (bot_id,)
        ).fetchone()
    if not wid or wid[0] != profile.workspace_id:
        raise Conflict("Compute profile does not belong to this workspace.")
    return profile


def configuration(self: CloudComputers, user, bot):
    config = self.config(bot.id)
    binding = self.binding(bot_id=bot.id)
    profile = self.profile_for(binding) if binding else self.profiles.get(config["profile_id"])
    self.require_manage(user, bot.id, profile)
    with self.store.transaction() as db:
        wid = db.execute(
            "SELECT workspace_id FROM bot_streams WHERE bot_id=?", (bot.id,)
        ).fetchone()[0]
    return {
        **config,
        "workspace_id": wid,
        "can_manage_compute": True,
        "binding": self.details(binding) if binding else None,
    }


async def select(self: CloudComputers, user, bot, command):
    from agentbot_control.shared_computers.resolution import bot_blocked

    if bot_blocked(self.store, bot.id):
        raise Conflict(
            "Per-bot cloud configuration is locked while this workspace shares one computer.",
            code="workspace_computer",
        )
    self.require_manage(user, bot.id)
    if bot.framework in {"ufo", "open_interface"}:
        raise Conflict("UFO bots use a paired Windows desktop.")
    async with self.mutex(bot.id):
        digest = {"operation": "cloud.select", **command.model_dump()}
        previous = self.store.receipt(bot.id, command.request_id, digest)
        if previous:
            return previous
        current = self.config(bot.id)
        computer = self.store.computer(bot.id)
        if (
            self.binding(bot_id=bot.id)
            or self.store.active(bot.id)
            or (computer and computer["status"] != "closed")
        ):
            raise Conflict("Close the current computer before changing providers.")
        if current["revision"] != command.expected_revision:
            raise Conflict("Computer configuration changed. Refresh settings.")
        if command.provider != "docker":
            profile = self.profiles.get(command.profile_id)
            with self.store.transaction() as db:
                wid = db.execute(
                    "SELECT workspace_id FROM bot_streams WHERE bot_id=?", (bot.id,)
                ).fetchone()
            if (
                not profile
                or profile.provider != command.provider
                or not wid
                or wid[0] != profile.workspace_id
            ):
                raise Conflict("Select an available profile for this workspace.")
            self.require_manage(user, bot.id, profile)
            if (
                "create" if command.ownership == "managed" else "attach"
            ) not in profile.allowed_operations:
                raise Conflict("This ownership mode is not enabled by the profile.")
        result = {
            "provider": command.provider,
            "profile_id": command.profile_id if command.provider != "docker" else None,
            "revision": current["revision"] + 1,
            "ownership": command.ownership,
        }
        with self.store.transaction() as db:
            db.execute(
                "INSERT INTO cloud_compute_config(bot_id,provider,profile_id,revision,ownership) VALUES (?,?,?,?,?) ON CONFLICT(bot_id) DO UPDATE SET provider=excluded.provider,profile_id=excluded.profile_id,revision=excluded.revision,ownership=excluded.ownership",
                (
                    bot.id,
                    result["provider"],
                    result["profile_id"],
                    result["revision"],
                    result["ownership"],
                ),
            )
            self.store._save_receipt(db, bot.id, command.request_id, digest, result)
        return result
