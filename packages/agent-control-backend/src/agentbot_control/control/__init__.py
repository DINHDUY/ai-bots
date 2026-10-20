"""Human leases fence every input and keep the agent paused after release."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agentbot.interfaces import ISandboxClient
    from agentbot.kernel import EngineRuntimeManager

    from agentbot_control.event_store import EventStore
    from agentbot_control.macos import MacComputers
    from agentbot_control.ports import StartRun, StopRun
    from agentbot_control.store import Catalog
    from agentbot_control.toolkit import Toolkit
    from agentbot_control.windows import WindowsComputers
    from agentbot_control.workspaces import Workspaces

import base64
import hashlib
import json
import math
import time
from datetime import UTC, datetime, timedelta
from typing import Literal

import anyio
from fastapi import HTTPException, Request, WebSocket
from pydantic import Field

from agentbot_control.auth import COOKIE_NAME
from agentbot_control.authorization import owned, request_bot
from agentbot_control.event_store import identifier, packed, stamp
from agentbot_control.schemas import Command, Conflict
from agentbot_control.transport import body, connected, send_bounded


class Acquire(Command):
    client_id: str = Field(min_length=8, max_length=128)
    generation: int = Field(ge=1)
    surface: Literal["browser", "desktop"] = "browser"


class LeaseCommand(Command):
    lease_id: str
    client_id: str
    fence: int


def digest(token):
    return hashlib.sha256(token.encode()).hexdigest()


class Control:
    def __init__(
        self,
        store: EventStore,
        *,
        catalog: Catalog,
        workspaces: Workspaces,
        kernel: EngineRuntimeManager,
        windows: WindowsComputers,
        toolkit: Toolkit,
        action_locks: dict[str, asyncio.Lock],
        bind: Callable[[dict], None],
        mutex: Callable[[str], asyncio.Lock],
        start: StartRun,
        stop: StopRun,
        tasks: dict[str, asyncio.Task],
        computer_existing: Callable[..., Awaitable[tuple[dict, ISandboxClient]]],
        computer_history: Callable[..., list[dict]],
        close_lease: Callable[[str], Awaitable[None]],
        macos: MacComputers | None = None,
    ) -> None:
        self.store = store
        self.catalog = catalog
        self.workspaces = workspaces
        self.kernel = kernel
        self.windows = windows
        self.macos = macos
        self.toolkit = toolkit
        self.action_locks = action_locks
        self.bind = bind
        self.mutex = mutex
        self.start = start
        self.stop = stop
        self.tasks = tasks
        self.computer_existing = computer_existing
        self.computer_history = computer_history
        self.close_lease = close_lease
        self.tokens = {}
        self.locks = {}
        self.last_input = {}

    def paused(self, bot_id):
        from agentbot_control.shared_computers.resolution import paused

        with self.store.transaction() as db:
            return paused(db, bot_id)

    def state(self, bot_id):
        from agentbot_control.shared_computers.resolution import lease_row

        with self.store.transaction() as db:
            row = lease_row(db, bot_id)
        recording = self.toolkit.recording(row["id"]) if row else None
        return {
            "paused": self.paused(bot_id),
            "lease": dict(row) if row else None,
            "recording": {k: recording[k] for k in ("id", "state", "private")}
            if recording
            else None,
        }

    def check(self, bot_id, sid, user, token, lease_id, client_id, fence):
        self.workspaces.bot(user.id, bot_id, "write")
        with self.store.transaction() as db:
            row = db.execute(
                "SELECT l.* FROM control_leases l JOIN computer_sessions s ON s.id=l.session_id WHERE l.id=? AND l.bot_id=? AND l.session_id=? AND l.user_id=? AND l.login_digest=? AND l.client_id=? AND l.fence=? AND l.status='active' AND l.expires_at>? AND s.status='running' AND l.generation=s.generation",
                (
                    lease_id,
                    bot_id,
                    sid,
                    user.id,
                    digest(token),
                    client_id,
                    fence,
                    stamp(),
                ),
            ).fetchone()
        if not row:
            raise Conflict("Control lease expired, revoked, or belongs to another tab.")
        return dict(row)

    async def acquire(self, bot_id, sid, user, token, command):
        return await leases.acquire(self, bot_id, sid, user, token, command)

    def renew(self, bot_id, sid, user, token, command):
        return leases.renew(self, bot_id, sid, user, token, command)

    async def input(self, bot_id, sid, user, token, message):
        return await input.input(self, bot_id, sid, user, token, message)

    async def release_by_id(self, lease_id):
        return await leases.release_by_id(self, lease_id)

    def retire(self, bot_id, sid):
        return leases.retire(self, bot_id, sid)

    async def resume(self, bot_id, sid, user, bot, command):
        if self.state(bot_id)["lease"]:
            raise Conflict(
                "Release human control and terminals before resuming.", code="human_control"
            )
        await self.computer_existing(bot_id, sid)
        return await self.start(
            user,
            bot,
            command.request_id,
            "Continue the previous task after operator changes. Re-observe workspace files and the screen before proposing actions.",
            "human_resume",
            resume_sid=sid,
        )

    async def sweep(self):
        while True:
            with self.store.transaction() as db:
                rows = db.execute(
                    "SELECT id,expires_at FROM control_leases WHERE status IN ('active','releasing')"
                ).fetchall()
            for row in rows:
                token = self.tokens.get(row["id"])
                if (
                    row["expires_at"] <= stamp()
                    or not token
                    or not self.catalog.user_from_token(token)
                ):
                    try:
                        await self.release_by_id(row["id"])
                    except Exception:
                        pass  # Retain releasing/paused until termination is confirmed.
            for rid in list(self.tasks):
                with self.store.transaction() as db:
                    run = db.execute(
                        "SELECT bot_id,user_id FROM runs WHERE id=?", (rid,)
                    ).fetchone()
                if run:
                    try:
                        self.workspaces.bot(run["user_id"], run["bot_id"], "write")
                    except HTTPException:
                        self.stop(run["bot_id"], rid, "authority_revoked_" + rid)
            self.store.health.progressed("control_leases")
            await asyncio.sleep(1)


def register_control_routes(app):
    return http.register_control_routes(app)


from agentbot_control.control import http, input, leases

__all__ = [
    "Acquire",
    "Awaitable",
    "COOKIE_NAME",
    "Callable",
    "Command",
    "Conflict",
    "Control",
    "Field",
    "HTTPException",
    "LeaseCommand",
    "Literal",
    "Request",
    "TYPE_CHECKING",
    "UTC",
    "WebSocket",
    "anyio",
    "asyncio",
    "base64",
    "body",
    "connected",
    "datetime",
    "digest",
    "hashlib",
    "http",
    "identifier",
    "input",
    "json",
    "leases",
    "math",
    "owned",
    "packed",
    "register_control_routes",
    "request_bot",
    "send_bounded",
    "stamp",
    "time",
    "timedelta",
]
