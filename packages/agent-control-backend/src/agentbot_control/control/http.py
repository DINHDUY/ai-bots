from __future__ import annotations

import asyncio
import json

import anyio
from fastapi import HTTPException, Request, WebSocket

from agentbot_control.auth import COOKIE_NAME
from agentbot_control.authorization import owned, request_bot
from agentbot_control.control import Acquire, LeaseCommand
from agentbot_control.schemas import Command, Conflict
from agentbot_control.transport import body, connected, send_bounded


def register_control_routes(app):
    service = app.state.runtime.control
    base = "/api/bots/{bot_id}/sessions/{sid}/control"

    @app.get(base)
    async def state(bot_id: str, sid: str, request: Request):
        request_bot(request, bot_id)
        return service.state(bot_id)

    @app.post(base + "/acquire")
    async def acquire(bot_id: str, sid: str, request: Request):
        user, _ = request_bot(request, bot_id)
        return await service.acquire(
            bot_id,
            sid,
            user,
            request.cookies[COOKIE_NAME],
            await body(request, Acquire),
        )

    @app.post(base + "/renew")
    async def renew(bot_id: str, sid: str, request: Request):
        user, _ = request_bot(request, bot_id)
        return service.renew(
            bot_id,
            sid,
            user,
            request.cookies[COOKIE_NAME],
            await body(request, LeaseCommand),
        )

    @app.post(base + "/release")
    async def release(bot_id: str, sid: str, request: Request):
        user, _ = request_bot(request, bot_id)
        command = await body(request, LeaseCommand)
        service.check(
            bot_id,
            sid,
            user,
            request.cookies[COOKIE_NAME],
            command.lease_id,
            command.client_id,
            command.fence,
        )
        await service.release_by_id(command.lease_id)
        return {"paused": True}

    @app.post(base + "/resume")
    async def resume(bot_id: str, sid: str, request: Request):
        user, bot = request_bot(request, bot_id)
        return await service.resume(bot_id, sid, user, bot, await body(request, Command))

    @app.websocket(base + "/ws")
    async def inputs(websocket: WebSocket, bot_id: str, sid: str):
        token = websocket.cookies.get(COOKIE_NAME)
        if websocket.headers.get("origin") not in (None, *app.state.cors_origins):
            await websocket.close(code=1008)
            return
        try:
            user, _ = owned(app.state.runtime.catalog, token, bot_id)
            lease_id = websocket.query_params["lease_id"]
            client_id = websocket.query_params["client_id"]
            fence = int(websocket.query_params["fence"])
            service.check(bot_id, sid, user, token, lease_id, client_id, fence)
        except (KeyError, ValueError, Conflict, HTTPException):
            await websocket.close(code=1008)
            return
        await websocket.accept()

        async def reader():
            while True:
                raw = await websocket.receive_text()
                if len(raw) > 4096:
                    raise RuntimeError("Input too large")
                try:
                    owned(app.state.runtime.catalog, token, bot_id)
                    message = json.loads(raw)
                    if not isinstance(message, dict) or any(
                        message.get(k) != v
                        for k, v in {
                            "lease_id": lease_id,
                            "client_id": client_id,
                            "fence": fence,
                        }.items()
                    ):
                        raise Conflict("Input belongs to another control connection.")
                    result = await service.input(bot_id, sid, user, token, message)
                    await send_bounded(websocket, result)
                except (Conflict, ValueError) as exc:
                    await send_bounded(websocket, {"status": "rejected", "detail": str(exc)})

        async def watchdog():
            while True:
                owned(app.state.runtime.catalog, token, bot_id)
                try:
                    service.check(bot_id, sid, user, token, lease_id, client_id, fence)
                except Conflict as exc:
                    raise RuntimeError(str(exc))
                await asyncio.sleep(1)

        try:
            await connected(websocket, reader(), watchdog())
        finally:
            with anyio.CancelScope(shield=True):
                await service.release_by_id(lease_id)
