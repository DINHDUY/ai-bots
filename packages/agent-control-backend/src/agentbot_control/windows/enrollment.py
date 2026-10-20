from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agentbot_control.event_store import EventStore
import asyncio
import json
import secrets
import time
from datetime import UTC, datetime, timedelta

from agentbot_windows import UFO_REVISION
from agentbot_windows.protocol import MAX_FRAME, Hello
from fastapi import HTTPException, Request, WebSocket, WebSocketDisconnect

from agentbot_control.authorization import request_bot
from agentbot_control.cloud import SelectCloud
from agentbot_control.event_store import identifier, stamp
from agentbot_control.schemas import Conflict
from agentbot_control.transport import body
from agentbot_control.windows.connection import Connection
from agentbot_control.windows.models import (
    CompleteEnrollment,
    Enrollment,
    SelectComputer,
    Takeover,
    token_hash,
)


class WindowsComputers:
    def __init__(self, store: EventStore, tasks: dict[str, asyncio.Task]) -> None:
        self.store, self.tasks = store, tasks
        self.connections = {}

    def config(self, bot_id):
        with self.store.transaction() as db:
            row = db.execute(
                "SELECT c.*,p.owner_id,p.revoked_at,p.name FROM bot_compute_config c JOIN paired_computers p ON p.id=c.device_id WHERE c.bot_id=?",
                (bot_id,),
            ).fetchone()
        return dict(row) if row else None

    def binding(self, sid):
        with self.store.transaction() as db:
            row = db.execute("SELECT * FROM windows_bindings WHERE session_id=?", (sid,)).fetchone()
        return dict(row) if row else None

    def connection(self, device_id):
        connection = self.connections.get(device_id)
        if not connection or connection.closed:
            raise Conflict(
                "Windows companion is offline. Open it on the paired PC.",
                code="computer_unavailable",
            )
        with self.store.transaction() as db:
            row = db.execute(
                "SELECT revoked_at FROM paired_computers WHERE id=?", (device_id,)
            ).fetchone()
        if not row or row[0]:
            raise Conflict("Windows computer enrollment revoked")
        return connection

    def require_run(self, bot, user_id):
        config = self.config(bot.id)
        if bot.framework != "ufo":
            if config:
                raise Conflict("This Windows computer requires the Microsoft UFO framework")
            return
        if not config or config["owner_id"] != user_id or config["revoked_at"]:
            raise Conflict("Pair and select a Windows computer in bot settings first")
        self.connection(config["device_id"]).check(write=True)

    def public(self, device):
        conn = self.connections.get(device["id"])
        online = bool(conn and not conn.closed and time.monotonic() - conn.last_seen < 12)
        return {
            "id": device["id"],
            "name": device["name"],
            "revoked": bool(device["revoked_at"]),
            "online": online,
            "state": conn.hello.model_dump(exclude={"windows_session", "epoch"})
            if online
            else None,
        }

    async def pause(self, device_id, reason):
        with self.store.transaction() as db:
            bindings = list(
                db.execute(
                    "SELECT * FROM windows_bindings WHERE device_id=? AND active=1",
                    (device_id,),
                )
            )
            for row in bindings:
                db.execute(
                    "INSERT INTO computer_control(session_id,paused) VALUES (?,1) ON CONFLICT(session_id) DO UPDATE SET paused=1,fence=fence+1",
                    (row["session_id"],),
                )
                self.store._event(db, row["bot_id"], "computer.local_paused", {"reason": reason})
        for row in bindings:
            run = self.store.active(row["bot_id"])
            if run:
                self.store.request_stop(row["bot_id"], run["id"], identifier("local_stop"))
                task = self.tasks.get(run["id"])
                if task:
                    task.cancel()

    def register(self, app):
        runtime, store = app.state.runtime, self.store

        @app.post("/api/bots/{bot_id}/computer/takeover")
        async def takeover(bot_id: str, request: Request):
            user, bot = request_bot(request, bot_id)
            if bot.framework == "open_interface":
                from agentbot_control.macos.schemas import Takeover as MacTakeover

                return await runtime.macos.takeover(
                    bot_id, await body(request, MacTakeover), runtime.mutex
                )
            command = await body(request, Takeover)
            async with runtime.mutex(bot_id):
                fingerprint = {"operation": "windows.takeover", **command.model_dump()}
                previous = store.receipt(bot_id, command.request_id, fingerprint)
                if previous:
                    return previous
                current = store.computer(bot_id)
                cfg = self.config(bot_id)
                if not cfg or not current or current["generation"] != command.generation:
                    raise Conflict("Windows computer generation changed")
                await self.pause(cfg["device_id"], "Human control requested")
                await self.connection(cfg["device_id"]).rpc("local_stop", timeout=5)
                result = {"paused": True, "local_control": False}
                with store.transaction() as db:
                    store._save_receipt(db, bot_id, command.request_id, fingerprint, result)
                return result

        @app.get("/api/computers")
        async def devices(request: Request):
            user = runtime.workspaces.user(request)
            with store.transaction() as db:
                rows = list(
                    db.execute(
                        "SELECT * FROM paired_computers WHERE owner_id=? AND revoked_at IS NULL",
                        (user.id,),
                    )
                )
            return {"computers": [self.public(r) for r in rows]}

        @app.post("/api/computers/enrollments")
        async def enrollment(request: Request):
            user = runtime.workspaces.user(request)
            command = await body(request, Enrollment)
            code = secrets.token_urlsafe(32)
            expires = (datetime.now(UTC) + timedelta(minutes=10)).isoformat()
            with store.transaction() as db:
                old = db.execute(
                    "SELECT id FROM computer_enrollments WHERE owner_id=? AND request_id=?",
                    (user.id, command.request_id),
                ).fetchone()
                if old:
                    raise Conflict(
                        "Enrollment code already issued. Create a new enrollment if it was lost."
                    )
                db.execute(
                    "INSERT INTO computer_enrollments VALUES (?,?,?,?,NULL,?)",
                    (
                        identifier("enroll"),
                        user.id,
                        token_hash(code),
                        expires,
                        command.request_id,
                    ),
                )
            return {"code": code, "expires_at": expires}

        @app.post("/api/computer-agents/enroll")
        async def complete(request: Request):
            command = await body(request, CompleteEnrollment)
            token, did = secrets.token_urlsafe(48), identifier("pc")
            with store.transaction() as db:
                row = db.execute(
                    "SELECT * FROM computer_enrollments WHERE secret_hash=? AND consumed_at IS NULL AND expires_at>?",
                    (token_hash(command.code), stamp()),
                ).fetchone()
                if not row:
                    raise HTTPException(403, "Enrollment expired or already used")
                db.execute(
                    "UPDATE computer_enrollments SET consumed_at=? WHERE id=?",
                    (stamp(), row["id"]),
                )
                db.execute(
                    "INSERT INTO paired_computers VALUES (?,?,?,?,?,NULL)",
                    (did, row["owner_id"], command.name, token_hash(token), stamp()),
                )
            return {"device_id": did, "token": token}

        @app.post("/api/computers/{device_id}/revoke")
        async def revoke(device_id: str, request: Request):
            user = runtime.workspaces.user(request)
            await body(request, Enrollment)
            with store.transaction() as db:
                if not db.execute(
                    "SELECT id FROM paired_computers WHERE id=? AND owner_id=?",
                    (device_id, user.id),
                ).fetchone():
                    raise HTTPException(404, "Computer not found")
                db.execute(
                    "UPDATE paired_computers SET revoked_at=COALESCE(revoked_at,?) WHERE id=?",
                    (stamp(), device_id),
                )
            await self.pause(device_id, "Device revoked")
            conn = self.connections.get(device_id)
            if conn:
                conn.disconnect()
                await conn.ws.close(code=1008)
            return {"revoked": True}

        @app.get("/api/bots/{bot_id}/compute-config")
        async def configuration(bot_id: str, request: Request):
            user, bot = request_bot(request, bot_id)
            if bot.framework == "open_interface":
                return await runtime.macos.configuration(user, bot)
            if bot.framework != "ufo":
                return runtime.cloud.configuration(user, bot)
            if user.id != bot.owner_id:
                raise HTTPException(403, "Computer configuration is owner-only")
            value = self.config(bot_id)
            return {
                "provider": "windows_local" if bot.framework == "ufo" else "docker",
                "device_id": value["device_id"] if value else None,
                "revision": value["revision"] if value else 0,
            }

        @app.post("/api/bots/{bot_id}/compute-config")
        async def select(bot_id: str, request: Request):
            user, bot = runtime.cloud.actor(request, bot_id)
            if bot.framework == "open_interface":
                from agentbot_control.macos.schemas import SelectComputer as MacSelect

                return await runtime.macos.select(
                    user, bot, await body(request, MacSelect), runtime.mutex
                )
            if bot.framework != "ufo":
                return await runtime.cloud.select(user, bot, await body(request, SelectCloud))
            command = await body(request, SelectComputer)
            if user.id != bot.owner_id or bot.framework != "ufo":
                raise HTTPException(403, "Only the owner of a UFO bot can pair its computer")
            async with runtime.mutex(bot_id):
                runtime.ensure(bot)
                fingerprint = {"operation": "windows.select", **command.model_dump()}
                previous = store.receipt(bot_id, command.request_id, fingerprint)
                if previous:
                    return previous
                current = store.computer(bot_id)
                if store.active(bot_id) or (current and current["status"] != "closed"):
                    raise Conflict("Close the current computer before changing its binding")
                with store.transaction() as db:
                    device = db.execute(
                        "SELECT id FROM paired_computers WHERE id=? AND owner_id=? AND revoked_at IS NULL",
                        (command.device_id, user.id),
                    ).fetchone()
                    if not device:
                        raise HTTPException(404, "Computer not found")
                    old = db.execute(
                        "SELECT revision FROM bot_compute_config WHERE bot_id=?",
                        (bot_id,),
                    ).fetchone()
                    revision = old[0] if old else 0
                    if revision != command.expected_revision:
                        raise Conflict("Computer configuration changed")
                    db.execute(
                        "INSERT INTO bot_compute_config VALUES (?,?,?) ON CONFLICT(bot_id) DO UPDATE SET device_id=excluded.device_id,revision=excluded.revision",
                        (bot_id, command.device_id, revision + 1),
                    )
                    result = {
                        "provider": "windows_local",
                        "device_id": command.device_id,
                        "revision": revision + 1,
                    }
                    store._save_receipt(db, bot_id, command.request_id, fingerprint, result)
                return result

        @app.websocket("/api/computer-agents/connect")
        async def connect(ws: WebSocket):
            token = ws.headers.get("authorization", "").removeprefix("Bearer ")
            with store.transaction() as db:
                row = db.execute(
                    "SELECT * FROM paired_computers WHERE token_hash=? AND revoked_at IS NULL",
                    (token_hash(token),),
                ).fetchone()
            if not row or ws.headers.get("origin"):
                await ws.close(code=1008)
                return
            await ws.accept()
            conn = None
            try:
                initial = await asyncio.wait_for(ws.receive_text(), 5)
                if len(initial.encode()) > 8192:
                    raise ValueError("Companion handshake too large")
                hello = Hello.model_validate_json(initial)
                if hello.ufo_revision != UFO_REVISION:
                    raise ValueError("Unsupported UFO build")
                old = self.connections.get(row["id"])
                if old and not old.closed:
                    raise ValueError("Another companion connection is active")
                conn = Connection(ws, token, hello)
                self.connections[row["id"]] = conn
                while True:
                    raw = await asyncio.wait_for(ws.receive_text(), 12)
                    if len(raw.encode()) > MAX_FRAME:
                        raise ValueError("Companion message too large")
                    value = json.loads(raw)
                    conn.last_seen = time.monotonic()
                    if value.get("type") == "status":
                        updated = Hello.model_validate(value["state"])
                        if (
                            updated.epoch != hello.epoch
                            or updated.windows_session != hello.windows_session
                            or updated.revision < conn.hello.revision
                        ):
                            raise ValueError("Companion identity changed")
                        changed = updated != conn.hello
                        conn.hello = updated
                        if changed and not (updated.armed and updated.sharing and updated.ready):
                            await self.pause(row["id"], updated.reason or "Local control disabled")
                        async with conn.send_lock:
                            await ws.send_json({"type": "heartbeat"})
                    else:
                        future = conn.pending.get(value.get("id"))
                        if future and not future.done():
                            future.set_result(value)
            except (WebSocketDisconnect, TimeoutError, ValueError):
                pass
            finally:
                if conn:
                    conn.disconnect()
                    if self.connections.get(row["id"]) is conn:
                        self.connections.pop(row["id"], None)
                    await self.pause(row["id"], "Windows companion disconnected")
                try:
                    await ws.close()
                except (RuntimeError, WebSocketDisconnect):
                    pass
