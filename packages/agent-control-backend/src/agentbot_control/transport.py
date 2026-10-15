"""V2 command/replay API and the legacy control-plane socket facade."""

import asyncio
import base64

import anyio
from fastapi import HTTPException, Request, WebSocket, WebSocketDisconnect
from pydantic import ValidationError

from agentbot_control.auth import COOKIE_NAME
from agentbot_control.authorization import owned, request_bot
from agentbot_control.db import DatabaseBusy
from agentbot_control.event_store import identifier
from agentbot_control.schemas import (
    CloseComputer,
    Command,
    Conflict,
    CreatePolicy,
    Decision,
    StartRun,
)
from agentbot_control.store import CatalogError


async def body(request, model):
    if (
        request.headers.get("content-type", "").split(";", 1)[0].lower()
        != "application/json"
    ):
        raise HTTPException(415, "Content-Type must be application/json.")
    try:
        return model.model_validate(await request.json())
    except (ValidationError, ValueError):
        raise HTTPException(422, "Invalid command body.")


def register_routes(app):
    runtime = app.state.runtime

    @app.exception_handler(DatabaseBusy)
    async def database_busy(_request, exc):
        from fastapi.responses import JSONResponse
        return JSONResponse({"detail": str(exc), "code": "database_busy"}, status_code=503, headers={"Retry-After": "1"})

    @app.exception_handler(Conflict)
    async def conflict(_request, exc):
        from fastapi.responses import JSONResponse

        status = {"worker_unavailable": 503, "capacity_limit": 429}.get(exc.code, 409)
        return JSONResponse({"detail": str(exc), "code": exc.code}, status_code=status, headers={"Retry-After": "5"} if status in {429, 503} else None)

    @app.get("/api/capabilities")
    async def capabilities(request: Request):
        if not app.state.catalog.user_from_token(request.cookies.get(COOKIE_NAME)):
            raise HTTPException(401, "Sign in required.")
        return runtime.capabilities

    @app.get("/api/bots/{bot_id}/snapshot")
    async def snapshot(bot_id: str, request: Request):
        _, bot = request_bot(request, bot_id)
        await runtime.store.offload(lambda: runtime.ensure(bot))
        return await runtime.store.offload(lambda: runtime.store.snapshot(bot_id))

    @app.get("/api/bots/{bot_id}/messages")
    async def messages(bot_id: str, request: Request, before: int | None = None):
        _, bot = request_bot(request, bot_id)
        runtime.ensure(bot)
        if before is not None and before < 1:
            raise HTTPException(422, "Invalid message cursor.")
        return await runtime.store.offload(lambda: runtime.store.messages(bot_id, before))

    @app.get("/api/bots/{bot_id}/events")
    async def events(bot_id: str, request: Request, after_seq: int = 0):
        _, bot = request_bot(request, bot_id)
        runtime.ensure(bot)
        if after_seq < 0:
            raise HTTPException(422, "Invalid event cursor.")
        return await runtime.store.offload(lambda: runtime.store.events(bot_id, after_seq))

    @app.post("/api/bots/{bot_id}/runs", status_code=202)
    async def start(bot_id: str, request: Request):
        user, bot = request_bot(request, bot_id)
        command = await body(request, StartRun)
        try:
            return await runtime.start(
                user,
                bot,
                command.request_id,
                command.prompt,
                attachment_ids=command.attachment_ids,
            )
        except CatalogError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.get("/api/bots/{bot_id}/runs/{run_id}")
    async def run(bot_id: str, run_id: str, request: Request):
        request_bot(request, bot_id)
        value = runtime.store.run(bot_id, run_id)
        if not value:
            raise HTTPException(404, "Run not found.")
        return value

    @app.post("/api/bots/{bot_id}/runs/{run_id}/stop", status_code=202)
    async def stop(bot_id: str, run_id: str, request: Request):
        request_bot(request, bot_id)
        command = await body(request, Command)
        try:
            return runtime.stop(bot_id, run_id, command.request_id)
        except KeyError:
            raise HTTPException(404, "Run not found.")

    @app.post("/api/bots/{bot_id}/approvals/{approval_id}/decision")
    async def decide(bot_id: str, approval_id: str, request: Request):
        user, _ = request_bot(request, bot_id)
        command = await body(request, Decision)
        try:
            return await runtime.decide(user, bot_id, approval_id, command)
        except KeyError:
            raise HTTPException(404, "Approval not found.")

    @app.post("/api/bots/{bot_id}/computer/close")
    async def close(bot_id: str, request: Request):
        user, bot = runtime.cloud.actor(request, bot_id) if runtime.cloud.selected(bot_id) else request_bot(request, bot_id)
        runtime.ensure(bot)
        command = await body(request, CloseComputer)
        return await runtime.close(bot_id, command.request_id, command.session_id, actor=user)

    @app.get("/api/bots/{bot_id}/approval-policies")
    async def policies(bot_id: str, request: Request):
        _, bot = request_bot(request, bot_id)
        runtime.ensure(bot)
        return runtime.policies.list(bot_id)

    @app.post("/api/bots/{bot_id}/approval-policies", status_code=201)
    async def create_policy(bot_id: str, request: Request):
        user, bot = request_bot(request, bot_id)
        runtime.ensure(bot)
        command = await body(request, CreatePolicy)
        try:
            return runtime.policies.create(bot_id, user.id, command)
        except KeyError:
            raise HTTPException(404, "Approval not found.")

    @app.post("/api/bots/{bot_id}/approval-policies/{policy_id}/revoke")
    async def revoke_policy(bot_id: str, policy_id: str, request: Request):
        user, _ = request_bot(request, bot_id)
        command = await body(request, Command)
        try:
            return runtime.policies.revoke(bot_id, policy_id, user.id, command)
        except KeyError:
            raise HTTPException(404, "Policy not found.")

    @app.get("/api/bots/{bot_id}/captures/{capture_id}")
    async def capture(bot_id: str, capture_id: str, request: Request):
        request_bot(request, bot_id)
        return runtime.store.captures.response(bot_id, capture_id)

    @app.websocket("/api/bots/{bot_id}/events/ws")
    async def subscription(websocket: WebSocket, bot_id: str):
        if (
            websocket.headers.get("origin") is not None
            and websocket.headers["origin"] not in app.state.cors_origins
        ):
            await websocket.close(code=1008)
            return
        token = websocket.cookies.get(COOKIE_NAME)
        try:
            _, bot = owned(app.state.catalog, token, bot_id)
            runtime.ensure(bot)
            raw = websocket.query_params.get("after_seq")
            cursor = int(raw) if raw is not None else None
            if cursor is not None and cursor < 0:
                raise ValueError()
        except (HTTPException, ValueError):
            await websocket.close(code=1008)
            return
        await websocket.accept()

        async def writer():
            nonlocal cursor
            store = runtime.store
            ready = False
            # Register before reading; clear before catch-up, never after it.
            with store.database.notifications.subscribe(bot_id) as changed:
                while True:
                    changed.clear()
                    await store.offload(lambda: owned(app.state.catalog, token, bot_id))
                    page = None if cursor is None else await store.offload(
                        lambda: store.events(bot_id, cursor)
                    )
                    if page is None or page["resync_required"]:
                        snap = await store.offload(lambda: store.snapshot(bot_id))
                        await store.offload(lambda: owned(app.state.catalog, token, bot_id))
                        await send_bounded(websocket, {"type": "snapshot", "data": snap})
                        cursor = snap["snapshot_seq"]
                    else:
                        for event in page["events"]:
                            await store.offload(lambda: owned(app.state.catalog, token, bot_id))
                            await send_bounded(websocket, event)
                            cursor = event["seq"]
                        if cursor < page["latest_seq"]:
                            continue
                    if not ready:
                        await send_bounded(websocket, {"type": "ready", "seq": cursor})
                        ready = True
                    try:
                        # Reconcile lost notifications and idle permission changes too.
                        await asyncio.wait_for(changed.wait(), timeout=5)
                    except TimeoutError:
                        pass

        async def reader():
            while True:
                await (
                    websocket.receive_text()
                )  # Subscription carries no execution commands.

        runtime.computers.observers[bot_id] = (
            runtime.computers.observers.get(bot_id, 0) + 1
        )
        try:
            await connected(websocket, reader(), writer())
        finally:
            runtime.computers.observers[bot_id] -= 1


async def send_bounded(websocket, frame):
    await asyncio.wait_for(websocket.send_json(frame), timeout=5)


async def connected(websocket, *workers):
    tasks = [asyncio.create_task(worker) for worker in workers]
    try:
        done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in done:
            try:
                task.result()
            except (WebSocketDisconnect, HTTPException, TimeoutError, RuntimeError):
                pass
    except asyncio.CancelledError:
        pass  # The ASGI server may cancel the handler as the peer disconnects.
    finally:
        with anyio.CancelScope(shield=True):
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            try:
                await websocket.close(code=1000)
            except (RuntimeError, WebSocketDisconnect):
                pass


def legacy_frame(store, event):
    kind, data, bot_id = event["type"], event["data"], event["bot_id"]
    if kind == "run.started":
        return {"event": "session", "session_id": bot_id}
    if kind == "message.created" and data["role"] == "assistant":
        return {"event": "log", "type": "RESULT", "payload": data["content"]}
    if kind == "approval.required":
        return {
            k: data[k] for k in ("event", "source", "approval_id", "action", "detail")
        }
    if kind == "observation":
        return data["frame"]
    if kind == "capture.available":
        raw = store.captures.read(bot_id, data["capture_id"])
        if raw is not None:
            return {
                "event": "log",
                "type": "SCREENSHOT_CAPTURE",
                "payload": base64.b64encode(raw).decode(),
            }
    if kind == "run.finished":
        if data["status"] == "completed":
            return {"event": "done", "session_id": bot_id}
        return {
            "event": "error",
            "session_id": bot_id,
            "payload": data["outcome"] or data["status"],
        }
    if kind == "session.closed":
        return {"event": "closed", "session_id": bot_id}


async def serve_legacy(websocket, runtime, user):
    bot_id = rid = None
    cursor = 0
    token = websocket.cookies.get(COOKIE_NAME)

    async def reader():
        nonlocal bot_id, rid, cursor
        while True:
            message = await websocket.receive_json()
            try:
                if not runtime.catalog.user_from_token(token):
                    raise HTTPException(401, "Sign in required.")
                if not isinstance(message, dict):
                    raise Conflict("JSON object required.")
                action = message.get("action")
                if action == "start":
                    if "framework" in message or "session_id" in message:
                        raise Conflict("Start a turn with bot_id and prompt.")
                    if rid and runtime.store.run(bot_id, rid)["status"] in (
                        "preparing",
                        "running",
                        "awaiting_approval",
                        "stopping",
                    ):
                        raise Conflict("A step is already running.", code='bot_busy')
                    _, bot = owned(
                        runtime.catalog, token, str(message.get("bot_id", ""))
                    )
                    command = StartRun(
                        request_id=identifier("legacy"),
                        prompt=message.get("prompt", ""),
                    )
                    runtime.ensure(bot)
                    before = runtime.store.snapshot(bot.id)["snapshot_seq"]
                    result = await runtime.start(
                        user, bot, command.request_id, command.prompt, "legacy"
                    )
                    bot_id, rid, cursor = bot.id, result["run_id"], before
                elif bot_id and action == "approve":
                    owned(runtime.catalog, token, bot_id)
                    command = Decision(
                        request_id=identifier("legacy"),
                        decision=message.get("decision"),
                    )
                    await runtime.decide(
                        user, bot_id, str(message.get("approval_id", "")), command
                    )
                elif bot_id and action == "stop":
                    owned(runtime.catalog, token, bot_id, "write")
                    runtime.stop(bot_id, rid, identifier("legacy"))
                elif bot_id and action == "close":
                    owned(runtime.catalog, token, bot_id, "write")
                    await runtime.close(bot_id, identifier("legacy"), actor=user)
                elif action == "close":
                    await send_bounded(
                        websocket, {"event": "closed", "session_id": None}
                    )
                else:
                    raise Conflict(f"Unknown action '{action}'.")
            except (
                Conflict,
                CatalogError,
                KeyError,
                ValidationError,
                HTTPException,
            ) as exc:
                detail = exc.detail if isinstance(exc, HTTPException) else str(exc)
                await send_bounded(websocket, {"event": "error", "payload": detail})

    async def writer():
        nonlocal cursor
        while True:
            if not runtime.catalog.user_from_token(token):
                return
            if bot_id:
                owned(runtime.catalog, token, bot_id)
                page = runtime.store.events(bot_id, cursor)
                if page["resync_required"]:
                    raise RuntimeError("Legacy stream fell behind retained history.")
                for event in page["events"]:
                    frame = legacy_frame(runtime.store, event)
                    if frame:
                        await send_bounded(websocket, frame)
                    cursor = event["seq"]
            await asyncio.sleep(0.05)

    try:
        await connected(websocket, reader(), writer())
    finally:
        if rid:
            task = runtime.tasks.get(rid)
            if task and not task.done():
                runtime.stop(bot_id, rid, identifier("legacy_disconnect"))
