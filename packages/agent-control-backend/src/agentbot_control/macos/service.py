"""Mac device registry and local-control reconciliation on the database worker."""

import asyncio
import time

from fastapi import HTTPException

from agentbot_control.event_store import EventStore, identifier
from agentbot_control.repositories import macos_devices as rows
from agentbot_control.schemas import Conflict


class MacComputers:
    def __init__(self, store: EventStore, tasks: dict[str, asyncio.Task]):
        self.store, self.tasks = store, tasks
        self.connections = {}
        self.configs = {}
        self.bindings = {}

    async def refresh(self):
        self.configs, self.bindings = await self.store.database.read(rows.snapshot)

    def config(self, bot_id):
        return self.configs.get(bot_id)

    def binding(self, sid):
        return self.bindings.get(sid)

    def connection(self, did):
        conn = self.connections.get(did)
        if not conn or conn.closed:
            raise Conflict("Mac companion is offline", code="computer_unavailable")
        return conn

    async def require_run(self, bot, user_id):
        if bot.framework != "open_interface":
            return
        await self.refresh()
        config = self.config(bot.id)
        if not config or config["owner_id"] != user_id or config["revoked_at"]:
            raise Conflict("Pair and select a Mac in bot settings first")
        self.connection(config["device_id"]).check(write=True)

    def public(self, device):
        conn = self.connections.get(device["id"])
        online = bool(conn and not conn.closed and time.monotonic() - conn.last_seen < 12)
        return {
            "id": device["id"],
            "name": device["name"],
            "provider": "macos_local",
            "revoked": bool(device["revoked_at"]),
            "online": online,
            "state": conn.hello.model_dump(exclude={"console_session", "epoch", "device_id"})
            if online and conn
            else None,
        }

    async def configuration(self, user, bot):
        if user.id != bot.owner_id:
            raise HTTPException(404, "Mac not found")
        await self.refresh()
        value = self.config(bot.id)
        return {
            "provider": "macos_local",
            "device_id": value["device_id"] if value else None,
            "revision": value["revision"] if value else 0,
        }

    async def select(self, user, bot, command, mutex):
        async with mutex(bot.id):
            result = await self.store.database.run(
                lambda db: rows.select(db, user.id, bot.id, command)
            )
            await self.refresh()
            return result

    async def pause(self, did, reason):
        active = await self.store.database.run(
            lambda db: rows.pause(db, did, reason, self.store._event)
        )
        for bid, rid in active:
            await self.store.offload(
                lambda: self.store.request_stop(bid, rid, identifier("mac_stop"))
            )
            task = self.tasks.get(rid)
            if task:
                task.cancel()

    async def takeover(self, bot_id, command, mutex):
        async with mutex(bot_id):
            fingerprint = {"operation": "macos.takeover", **command.model_dump()}
            previous = await self.store.offload(
                lambda: self.store.receipt(bot_id, command.request_id, fingerprint)
            )
            if previous:
                return previous
            await self.refresh()
            current = await self.store.offload(lambda: self.store.computer(bot_id))
            config = self.config(bot_id)
            if not config or not current or current["generation"] != command.generation:
                raise Conflict("Mac computer generation changed")
            await self.pause(config["device_id"], "Human control requested")
            await self.connection(config["device_id"]).rpc("local_stop", timeout=5)
            result = {"paused": True, "local_control": False}
            await self.store.database.run(
                lambda db: self.store._save_receipt(
                    db, bot_id, command.request_id, fingerprint, result
                )
            )
            return result

    async def shutdown(self):
        for conn in list(self.connections.values()):
            conn.disconnect()
            await conn.ws.close(code=1001)
