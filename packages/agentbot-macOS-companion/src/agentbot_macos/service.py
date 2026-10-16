"""Outbound authenticated connection and independently supervised native operations."""

from __future__ import annotations

import asyncio
import json
import time
import uuid

from agentbot_macos.actions import Permit
from agentbot_macos.protocol import MAX_FRAME, Envelope, Hello, packed
from agentbot_macos.receipts import ReceiptJournal
from agentbot_macos.results import NotDispatched, unknown
from agentbot_macos.session import permissions
from agentbot_macos.state import LocalState
from agentbot_macos.worker import Worker


class Companion:
    def __init__(
        self, credentials, source, manifest, journal, *, session_check=permissions, worker=None
    ):
        self.credentials = credentials
        self.state = LocalState()
        self.worker = worker or Worker(source, manifest)
        self.journal = ReceiptJournal(journal)
        self.session_check = session_check
        self.epoch = uuid.uuid4().hex
        self.status = "Disconnected"
        self.running = True
        self.tasks = set()
        self.mutations = asyncio.Lock()
        self.automating = False

    def hello(self) -> Hello:
        health = self.session_check()
        return Hello(
            device_id=self.credentials["device_id"],
            epoch=self.epoch,
            console_session=health["console_session"],
            name=self.credentials["name"],
            revision=self.state.revision,
            sharing=self.state.sharing,
            armed=self.state.armed,
            ready=health["ready"],
            screen_recording=health["screen_recording"],
            accessibility=health["accessibility"],
            reason=(health["reason"] or self.state.reason)[:300],
            scope=self.state.scope,
        )

    async def local_stop(self, reason="Stopped locally"):
        self.state.stop(reason)
        self.automating = False
        await self.worker.stop()

    async def execute(self, arguments: dict) -> dict:
        async with self.mutations:
            try:
                revision = self.state.check(write=True)
                permit = Permit.model_validate(arguments)
                permit.verify(self.credentials["token"], self.hello())
                previous = await asyncio.to_thread(self.journal.claim, permit)
            except Exception as exc:
                return NotDispatched(str(exc)).result()
            if previous is not None:
                if previous.get("outcome_unknown"):
                    await self.local_stop(previous["text"])
                return previous

            def check():
                try:
                    self.state.check(write=True)
                    permit.verify(self.credentials["token"], self.hello())
                except Exception as exc:
                    raise NotDispatched(str(exc)) from exc

            try:
                result = await self.worker.call(
                    "execute",
                    {
                        "action": permit.action.model_dump(),
                        "scope": self.state.scope,
                        "window": self.state.window,
                        "revision": revision,
                        "expires_at": permit.expires_at,
                    },
                    check,
                    permit.expires_at,
                )
            except NotDispatched as exc:
                result = exc.result()
            except BaseException as exc:
                result = unknown(
                    "Native worker interrupted; inspect the application before continuing"
                )
                await self.local_stop(result["text"])
                await asyncio.to_thread(self.journal.finish, permit.action_id, result)
                if not isinstance(exc, Exception):
                    raise
                return result
            if result.get("outcome_unknown"):
                await self.local_stop(result["text"])
            await asyncio.to_thread(self.journal.finish, permit.action_id, result)
            return result

    async def dispatch(self, message: Envelope):
        method, args = message.method, message.arguments
        if time.time() > message.deadline:
            raise ValueError("Request deadline expired")
        if method in {"health", "capabilities"}:
            return self.hello().model_dump()
        if method == "local_stop":
            await self.local_stop("Human control requested; enable control locally to resume")
            return {"stopped": True}
        if method == "cancel":
            self.automating = False
            await self.worker.stop()
            return {"stopped": True}
        if method == "action_status":
            if set(args) != {"action_id"} or not isinstance(args["action_id"], str):
                raise ValueError("Action identity required")
            return await asyncio.to_thread(self.journal.status, args["action_id"])
        if method == "execute":
            return await self.execute(args)
        revision = self.state.check()
        session = self.hello().console_session

        def check():
            self.state.check()
            hello = self.hello()
            if (
                not hello.ready
                or session != hello.console_session
                or self.state.revision != revision
            ):
                raise NotDispatched(hello.reason or "Local consent changed")

        check()
        if method in {"capture", "observe"}:
            if args:
                raise ValueError("Observation scope is selected locally")
            args = {"scope": self.state.scope, "window": self.state.window, "revision": revision}
        if method == "planner":
            self.automating = True
        result = await self.worker.call(method, args, check, message.deadline)
        check()
        return result

    async def run(self):
        from websockets.asyncio.client import connect

        base = self.credentials["backend"].rstrip("/")
        url = (
            "wss://" + base[8:] if base.startswith("https://") else "ws://" + base[7:]
        ) + "/api/macos-agents/connect"
        while self.running:
            try:
                async with connect(
                    url,
                    additional_headers={"Authorization": "Bearer " + self.credentials["token"]},
                    max_size=MAX_FRAME,
                    open_timeout=10,
                ) as ws:
                    self.epoch = uuid.uuid4().hex
                    self.state.stop("Connected; enable control locally")
                    self.state.last_contact = time.monotonic()
                    await ws.send(self.hello().model_dump_json())
                    self.status = "Connected"
                    send_lock = asyncio.Lock()
                    timer = asyncio.create_task(self.heartbeat(ws, send_lock))
                    try:
                        async for raw in ws:
                            self.state.last_contact = time.monotonic()
                            value = json.loads(raw)
                            if value.get("type") == "heartbeat":
                                continue
                            message = Envelope.model_validate(value)
                            if len(self.tasks) >= 8:
                                raise RuntimeError("Companion queue full")
                            task = asyncio.create_task(self.handle(message, ws, send_lock))
                            self.tasks.add(task)
                            task.add_done_callback(self.finished)
                    finally:
                        timer.cancel()
                        for task in list(self.tasks):
                            task.cancel()
                        await asyncio.gather(timer, *self.tasks, return_exceptions=True)
            except Exception:
                self.status = "Disconnected; reconnecting"
            finally:
                await self.local_stop("Connection ended; explicitly re-enable local control")
            if self.running:
                await asyncio.sleep(3)

    def finished(self, task):
        self.tasks.discard(task)
        if not task.cancelled():
            task.exception()

    async def heartbeat(self, ws, send_lock):
        session = self.hello().console_session
        while True:
            health = self.hello()
            if (not health.ready or health.console_session != session) and self.state.armed:
                await self.local_stop(health.reason or "Console session changed")
            if time.monotonic() - self.state.last_contact > 15:
                await self.local_stop("Backend heartbeat lost")
                await ws.close()
                return
            async with send_lock:
                await ws.send(packed({"type": "status", "state": self.hello().model_dump()}))
            await asyncio.sleep(1)

    async def handle(self, message, ws, send_lock):
        try:
            result = await self.dispatch(message)
            reply = {"id": message.id, "result": result}
        except Exception as exc:
            reply = {"id": message.id, "error": str(exc)[:500]}
        async with send_lock:
            await ws.send(packed({"type": "status", "state": self.hello().model_dump()}))
            await ws.send(packed(reply))
