"""Owner HTTP commands and companion-initiated authenticated WebSocket transport."""

import asyncio
import json
import time

from agentbot_macos.protocol import MAX_FRAME, Hello
from fastapi import Request, WebSocket, WebSocketDisconnect

from agentbot_control.macos.connection import Connection
from agentbot_control.macos.schemas import CompleteEnrollment
from agentbot_control.repositories import macos_devices as rows
from agentbot_control.schemas import Command
from agentbot_control.transport import body


def register_routes(app):
    runtime = app.state.runtime
    service = runtime.macos
    database = service.store.database

    @app.get("/api/macos-computers")
    async def devices(request: Request):
        user = runtime.workspaces.user(request)
        records = await database.read(lambda db: rows.list_devices(db, user.id))
        return {"computers": [service.public(r) for r in records]}

    @app.post("/api/macos-computers/enrollments")
    async def enrollment(request: Request):
        user = runtime.workspaces.user(request)
        command = await body(request, Command)
        return await database.run(lambda db: rows.enroll(db, user.id, command.request_id))

    @app.post("/api/macos-agents/enroll")
    async def complete(request: Request):
        command = await body(request, CompleteEnrollment)
        return await database.run(lambda db: rows.complete(db, command.code, command.name))

    @app.post("/api/macos-computers/{device_id}/revoke")
    async def revoke(device_id: str, request: Request):
        user = runtime.workspaces.user(request)
        await body(request, Command)
        await database.run(lambda db: rows.revoke(db, user.id, device_id))
        await service.refresh()
        await service.pause(device_id, "Mac pairing revoked")
        conn = service.connections.get(device_id)
        if conn:
            conn.disconnect()
            await conn.ws.close(code=1008)
        return {"revoked": True}

    @app.websocket("/api/macos-agents/connect")
    async def connect(ws: WebSocket):
        token = ws.headers.get("authorization", "").removeprefix("Bearer ")
        row = await database.read(lambda db: rows.authenticate(db, token))
        if not row or ws.headers.get("origin"):
            await ws.close(code=1008)
            return
        await ws.accept()
        conn = None
        try:
            raw = await asyncio.wait_for(ws.receive_text(), 5)
            if len(raw.encode()) > 8192:
                raise ValueError("Handshake too large")
            hello = Hello.model_validate_json(raw)
            if hello.device_id != row["id"]:
                raise ValueError("Wrong paired identity")
            old = service.connections.get(row["id"])
            if old and not old.closed:
                raise ValueError("Mac already connected")
            conn = Connection(ws, token, hello)
            service.connections[row["id"]] = conn
            await service.refresh()
            while True:
                raw = await asyncio.wait_for(ws.receive_text(), 12)
                if len(raw.encode()) > MAX_FRAME:
                    raise ValueError("Companion frame too large")
                value = json.loads(raw)
                conn.last_seen = time.monotonic()
                if value.get("type") == "status":
                    updated = Hello.model_validate(value["state"])
                    if (updated.device_id, updated.epoch, updated.console_session) != (
                        hello.device_id,
                        hello.epoch,
                        hello.console_session,
                    ) or updated.revision < conn.hello.revision:
                        raise ValueError("Companion identity changed")
                    changed = updated != conn.hello
                    conn.hello = updated
                    if changed and not (updated.ready and updated.sharing and updated.armed):
                        await service.pause(row["id"], updated.reason or "Mac control disabled")
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
                if service.connections.get(row["id"]) is conn:
                    service.connections.pop(row["id"], None)
                await service.pause(row["id"], "Mac companion disconnected")
            try:
                await ws.close()
            except (RuntimeError, WebSocketDisconnect):
                pass
