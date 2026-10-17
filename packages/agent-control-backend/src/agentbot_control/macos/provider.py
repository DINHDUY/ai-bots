"""Add Mac routing without changing the existing Windows/Docker provider behavior."""

import time

from agentbot_control.macos.connection import MacConnectionRejected
from agentbot_control.macos.sandbox import MacSandbox
from agentbot_control.repositories import macos_devices as rows
from agentbot_control.schemas import Conflict


class MacProviderRouter:
    def __init__(self, inner, computers):
        self.inner, self.computers = inner, computers
        self.bound = {}
        self.clients = {}

    @property
    def legacy(self):
        return self.inner.legacy

    def configure_scope(self, namespace, deployment):
        self.inner.configure_scope(namespace, deployment)

    def bind(self, sid, bot_id, generation):
        self.bound[sid] = (bot_id, generation)
        if not self.computers.config(bot_id):
            self.inner.bind(sid, bot_id, generation)

    def is_macos(self, sid):
        return bool(
            self.computers.binding(sid)
            or (sid in self.bound and self.computers.config(self.bound[sid][0]))
        )

    def is_windows(self, sid):
        return self.inner.is_windows(sid)

    async def legacy_candidate(self, bot_id):
        if self.computers.config(bot_id):
            return None
        return await self.inner.legacy_candidate(bot_id)

    async def get_or_create(self, sid):
        if not self.is_macos(sid):
            return await self.inner.get_or_create(sid)
        bot_id, generation = self.bound[sid]
        cfg = self.computers.config(bot_id)
        try:
            self.computers.connection(cfg["device_id"]).check()
            binding = await self.computers.store.database.run(
                lambda db: rows.claim_binding(db, bot_id, sid, generation)
            )
        except Conflict as exc:
            # These checks run before any RPC. A rejected claim rolls back on the
            # database worker, so lifecycle can retire this unused session safely.
            raise MacConnectionRejected(str(exc), code=exc.code) from exc
        self.computers.bindings[sid] = binding
        return await self.existing(sid)

    async def existing(self, sid):
        if not self.is_macos(sid):
            return await self.inner.existing(sid)
        binding = self.computers.binding(sid)
        if not binding or not binding["active"]:
            raise Conflict("Mac is disconnected from this bot")
        if sid not in self.clients:
            self.clients[sid] = MacSandbox(self.computers, binding)
        return self.clients[sid]

    async def inspect(self, sid):
        if not self.is_macos(sid):
            return await self.inner.inspect(sid)
        binding = self.computers.binding(sid)
        config = self.computers.config(self.bound[sid][0]) if sid in self.bound else None
        device = binding or config
        conn = self.computers.connections.get(device["device_id"]) if device else None
        online = bool(conn and not conn.closed and time.monotonic() - conn.last_seen < 12)
        ready = bool(
            binding
            and binding["active"]
            and online
            and conn
            and conn.hello.ready
            and conn.hello.sharing
        )
        reason = "Mac companion is offline"
        if online and conn:
            try:
                conn.check(write=True)
                reason = (
                    ""
                    if binding and binding["active"]
                    else "Select Connect Mac to connect this bot"
                )
            except Conflict as exc:
                reason = str(exc)
        return {
            "lifecycle": "running" if binding and binding["active"] else "missing",
            "provider": "macos_local",
            "compatible": ready,
            "services": {"desktop": ready},
            "local_control": bool(ready and conn and conn.hello.armed),
            "reason": reason,
            "name": conn.hello.name if conn else "Mac",
        }

    async def reconcile(self, sid, uncertain):
        if self.is_macos(sid):
            return "running"
        return await self.inner.reconcile(sid, uncertain)

    async def close(self, sid):
        if not self.is_macos(sid):
            return await self.inner.close(sid)
        binding = self.computers.binding(sid)
        conn = self.computers.connections.get(binding["device_id"]) if binding else None
        if conn and not conn.closed:
            await conn.rpc("local_stop", timeout=5)
        await self.computers.store.database.run(lambda db: rows.close_binding(db, sid))
        if binding:
            binding["active"] = 0
        self.clients.pop(sid, None)

    async def hibernate(self, sid):
        if self.is_macos(sid):
            raise Conflict("Use Disconnect for a personal Mac")
        return await self.inner.hibernate(sid)

    async def resume(self, sid):
        if self.is_macos(sid):
            raise Conflict("Reconnect and explicitly resume the Mac")
        return await self.inner.resume(sid)
