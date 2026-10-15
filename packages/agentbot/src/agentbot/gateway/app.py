"""WebSocket gateway that streams kernel event frames."""

from __future__ import annotations

import asyncio
import logging
import os
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect

from agentbot.bootstrap import build_kernel
from agentbot.events import RealTimeEventStreamer
from agentbot.kernel import EngineRuntimeManager, validate_session_id

logger = logging.getLogger("AgentBotKernel")




def create_app(kernel: EngineRuntimeManager | None = None) -> FastAPI:
    runtime = kernel or build_kernel()
    idle_seconds = float(os.environ.get("SESSION_IDLE_SECONDS", "900"))
    approval_timeout = float(os.environ.get("APPROVAL_TIMEOUT_SECONDS", "120"))

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        sweeper = asyncio.create_task(_sweep_idle(runtime, idle_seconds))
        yield
        sweeper.cancel()

    app = FastAPI(title="Agent Bot Gateway", lifespan=lifespan)
    app.state.kernel = runtime

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.websocket("/ws")
    async def websocket_endpoint(websocket: WebSocket) -> None:
        await websocket.accept()
        await _serve(websocket, app.state.kernel, approval_timeout)

    return app


async def _sweep_idle(kernel: EngineRuntimeManager, idle_seconds: float) -> None:
    while True:
        await asyncio.sleep(min(30.0, idle_seconds))
        try:
            closed = await kernel.close_idle(idle_seconds)
        except Exception:
            logger.exception("Idle sweep failed")
            continue
        if closed:
            logger.info("Closed idle sessions: %s", ", ".join(closed))


async def _serve(websocket: WebSocket, kernel: EngineRuntimeManager, approval_timeout: float) -> None:
    streamer = RealTimeEventStreamer(approval_timeout=approval_timeout)
    step_task: asyncio.Task[None] | None = None
    session_id: str | None = None

    async def reader() -> None:
        nonlocal step_task, session_id
        while True:
            message = await websocket.receive_json()
            action = message.get("action")
            if session_id:
                kernel.touch(session_id)
            if action == "approve":
                streamer.resolve(str(message.get("approval_id", "")), message.get("decision") == "approve")
            elif action == "stop":
                if step_task is not None and not step_task.done():
                    step_task.cancel()
            elif action == "close":
                if step_task is not None and not step_task.done():
                    step_task.cancel()
                if session_id:
                    await kernel.close_session(session_id)
                await websocket.send_json({"event": "closed", "session_id": session_id})
            elif action == "start":
                if step_task is not None and not step_task.done():
                    await websocket.send_json({"event": "error", "payload": "A step is already running."})
                    continue
                session_id = str(message.get("session_id") or uuid.uuid4().hex[:16])
                try:
                    validate_session_id(session_id)
                except ValueError as exc:
                    await websocket.send_json({"event": "error", "payload": str(exc)})
                    continue
                framework = str(message.get("framework", ""))
                prompt = str(message.get("prompt", ""))
                await websocket.send_json({"event": "session", "session_id": session_id})
                step_task = asyncio.create_task(
                    _run_step(websocket, kernel, streamer, framework, prompt, session_id)
                )
            else:
                await websocket.send_json({"event": "error", "payload": f"Unknown action '{action}'."})

    try:
        await reader()
    except WebSocketDisconnect:
        if step_task is not None and not step_task.done():
            step_task.cancel()
    finally:
        if step_task is not None:
            await asyncio.gather(step_task, return_exceptions=True)


async def _run_step(
    websocket: WebSocket,
    kernel: EngineRuntimeManager,
    streamer: RealTimeEventStreamer,
    framework: str,
    prompt: str,
    session_id: str,
) -> None:
    try:
        async for frame in kernel.process_agent_request(framework, prompt, session_id, streamer):
            await websocket.send_json(frame)
        await websocket.send_json({"event": "done", "session_id": session_id})
    except asyncio.CancelledError:
        await websocket.send_json({"event": "error", "payload": "cancelled", "session_id": session_id})
        raise
    except Exception as exc:
        logger.exception("Agent step failed")
        await websocket.send_json({"event": "error", "payload": str(exc), "session_id": session_id})


def main() -> None:
    import uvicorn

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    uvicorn.run(
        "agentbot.gateway.app:app",
        host=os.environ.get("HOST", "127.0.0.1"),
        port=int(os.environ.get("PORT", "8000")),
        factory=False,
    )


app = create_app()
