from __future__ import annotations

import time

from agentbot.interfaces import (
    SandboxManager,
)

from agentbot_control.schemas import Conflict
from agentbot_control.windows.sandbox import WindowsSandbox


class ProviderRouter:
    """Retain local Docker behavior; Windows close only retires an owned binding."""

    def __init__(self, docker, computers):
        self.docker, self.computers = docker, computers
        self.bound = {}
        self.clients = {}

    def __getattr__(self, key):
        return getattr(self.docker, key)

    def configure_scope(self, namespace, deployment):
        if isinstance(self.docker, SandboxManager):
            self.docker.configure_scope(namespace, deployment)

    def bind(self, sid, bot_id, generation):
        self.bound[sid] = (bot_id, generation)
        if not self.computers.config(bot_id):
            if isinstance(self.docker, SandboxManager):
                self.docker.bind(sid, bot_id, generation)

    def is_windows(self, sid):
        return bool(
            self.computers.binding(sid)
            or (sid in self.bound and self.computers.config(self.bound[sid][0]))
        )

    async def legacy_candidate(self, bot_id):
        if self.computers.config(bot_id):
            return None
        return (
            await self.docker.legacy_candidate(bot_id)
            if isinstance(self.docker, SandboxManager)
            else None
        )

    async def get_or_create(self, sid):
        if not self.is_windows(sid):
            return await self.docker.get_or_create(sid)
        bot_id, generation = self.bound[sid]
        cfg = self.computers.config(bot_id)
        self.computers.connection(cfg["device_id"]).check()
        with self.computers.store.transaction() as db:
            taken = db.execute(
                "SELECT session_id FROM windows_bindings WHERE device_id=? AND active=1 AND session_id!=?",
                (cfg["device_id"], sid),
            ).fetchone()
            if taken:
                raise Conflict("Another bot is bound to this Windows desktop. Disconnect it first.")
            db.execute(
                "INSERT OR IGNORE INTO windows_bindings VALUES (?,?,?,?,1)",
                (sid, bot_id, cfg["device_id"], generation),
            )
        return await self.existing(sid)

    async def existing(self, sid):
        if not self.is_windows(sid):
            return await self.docker.existing(sid)
        binding = self.computers.binding(sid)
        if not binding or not binding["active"]:
            raise Conflict("Windows computer is disconnected from this bot")
        return self.clients.setdefault(sid, WindowsSandbox(self.computers, binding))

    async def inspect(self, sid):
        if not self.is_windows(sid):
            return await self.docker.inspect(sid)
        binding = self.computers.binding(sid)
        if not binding or not binding["active"]:
            return {
                "lifecycle": "missing",
                "compatible": False,
                "services": {},
                "provider": "windows_local",
            }
        conn = self.computers.connections.get(binding["device_id"])
        ready = bool(
            conn
            and not conn.closed
            and time.monotonic() - conn.last_seen < 12
            and conn.hello.ready
            and conn.hello.sharing
        )
        return {
            "lifecycle": "running",
            "provider": "windows_local",
            "compatible": ready,
            "services": {"desktop": ready},
            "local_control": bool(ready and conn.hello.armed),
            "reason": conn.hello.reason if conn else "Windows companion offline",
            "name": conn.hello.name if conn else "Windows PC",
        }

    async def reconcile(self, sid, uncertain):
        if self.is_windows(sid):
            return "running"  # Runs/leases are interrupted separately; never touch the PC.
        return (
            await self.docker.reconcile(sid, uncertain)
            if isinstance(self.docker, SandboxManager)
            else "running"
        )

    async def close(self, sid):
        if not self.is_windows(sid):
            return await self.docker.close(sid)
        binding = self.computers.binding(sid)
        conn = self.computers.connections.get(binding["device_id"]) if binding else None
        if conn and not conn.closed:
            await conn.rpc("local_stop", timeout=5)
        self.clients.pop(sid, None)
        with self.computers.store.transaction() as db:
            db.execute("UPDATE windows_bindings SET active=0 WHERE session_id=?", (sid,))

    async def hibernate(self, sid):
        if self.is_windows(sid):
            raise Conflict("Use Disconnect for a personal Windows PC")
        return await self.docker.hibernate(sid)

    async def resume(self, sid):
        if self.is_windows(sid):
            raise Conflict(
                "Reconnect the Windows companion and explicitly resume the agent",
                code="computer_unavailable",
            )
        return await self.docker.resume(sid)
