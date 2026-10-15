"""Outbound companion connection with independent heartbeat and cancellation."""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path

from . import UFO_REVISION
from .execution import ActionNotDispatched, uncertain_result
from .protocol import MAX_FRAME, Hello, Permit, packed
from .state import LocalState, ReceiptJournal


class WorkerStopped(RuntimeError):
    def __init__(self, reason, *, dispatched=False):
        self.reason, self.dispatched = reason, dispatched
        phase = "during request" if dispatched else "before dispatch"
        super().__init__(f"Windows worker stopped {phase}: {reason}")


class Worker:
    def __init__(self, source, kind, scope="window"):
        self.source, self.kind, self.scope = source, kind, scope
        self.process = None
        self.job = None
        self.lock = asyncio.Lock()
        self.window = 0
        self.window_identity = (0, 0.0)
        self.fence = 0
        self.stop_reason = "Worker stopped"

    async def call(self, method, arguments=None, *, preflight=None, expires_at=None):
        def check():
            if preflight:
                try:
                    preflight()
                except ActionNotDispatched:
                    raise
                except Exception as exc:
                    if method == "execute":
                        raise ActionNotDispatched(str(exc)) from exc
                    raise

        fence = self.fence
        async with self.lock:
            if fence != self.fence:
                raise WorkerStopped(self.stop_reason)
            check()
            if self.process is None:
                env = dict(os.environ)
                # Only our source is placed on the import path. Do not inherit an
                # arbitrary PYTHONPATH or model credentials into a UFO child.
                for key in list(env):
                    if any(
                        word in key.upper()
                        for word in ("API_KEY", "ACCESS_TOKEN", "SECRET", "PASSWORD")
                    ):
                        env.pop(key, None)
                env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1])
                self.process = await asyncio.create_subprocess_exec(
                    sys.executable,
                    "-m",
                    "agentbot_windows.worker",
                    "--source",
                    str(self.source),
                    "--kind",
                    self.kind,
                    "--scope",
                    self.scope,
                    "--window",
                    str(self.window),
                    "--window-pid",
                    str(self.window_identity[0]),
                    "--window-created",
                    str(self.window_identity[1]),
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.DEVNULL,
                    limit=MAX_FRAME + 1,
                    env=env,
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
                )
            proc = self.process
            dispatched = False
            try:
                if os.name == "nt" and self.job is None:
                    from .win_session import worker_job

                    self.job = worker_job(proc.pid)
                if fence != self.fence:
                    raise WorkerStopped(self.stop_reason)
                check()
                proc.stdin.write(
                    (
                        packed(
                            {
                                "method": method,
                                "arguments": arguments or {},
                                "expires_at": expires_at,
                            }
                        )
                        + "\n"
                    ).encode()
                )
                dispatched = True
                await proc.stdin.drain()
                line = await asyncio.wait_for(proc.stdout.readline(), 45)
                if not line or len(line) > MAX_FRAME:
                    raise RuntimeError(
                        "Windows worker ended or exceeded its response limit"
                    )
                result = json.loads(line)
                if result.get("error"):
                    raise RuntimeError(result["error"])
                return result["result"]
            except BaseException as exc:
                interrupted = fence != self.fence
                reason = self.stop_reason if interrupted else "Worker request failed"
                await self.stop(reason)
                if interrupted and isinstance(exc, Exception):
                    raise WorkerStopped(reason, dispatched=dispatched) from exc
                if not dispatched and method == "execute" and isinstance(exc, Exception):
                    raise ActionNotDispatched(str(exc)) from exc
                raise

    async def stop(self, reason="Worker stopped"):
        self.fence += 1
        self.stop_reason = reason
        proc, self.process = self.process, None
        job, self.job = self.job, None
        try:
            if proc and proc.returncode is None:
                proc.kill()
                await proc.wait()
        finally:
            if job is not None:
                job.Close()


class Companion:
    def __init__(self, credentials, source, journal, *, session_check, state=None):
        self.credentials, self.source = credentials, source
        self.state = state or LocalState()
        self.journal = ReceiptJournal(journal)
        self.session_check = session_check
        self.epoch = uuid.uuid4().hex
        self.desktop = Worker(source, "desktop")
        self.planner = Worker(source, "planner")
        self.running = True
        self.status = "Disconnected"
        self.scope = "window"
        self.tasks = set()
        self.automating = False

    def hello(self):
        ready, session, reason = self.session_check()
        return Hello(
            epoch=self.epoch,
            windows_session=session,
            name=self.credentials["name"],
            revision=self.state.revision,
            sharing=self.state.sharing,
            armed=self.state.armed,
            ready=ready,
            reason=reason or self.state.reason,
            ufo_revision=UFO_REVISION,
        )

    async def stop_workers(self, reason="Task ended"):
        self.automating = False
        await asyncio.gather(self.desktop.stop(reason), self.planner.stop(reason))

    async def local_stop(self, reason="Stopped locally"):
        self.state.stop(reason)
        await self.stop_workers(reason)

    async def dispatch(self, message):
        method, arguments = message["method"], message.get("arguments", {})
        if method == "execute":
            return await self.execute(arguments)
        if method == "local_stop":
            await self.local_stop(
                "Human control requested; enable control locally before resuming"
            )
            return {"stopped": True}
        if method == "cancel":
            # End planning/execution without revoking the user's explicit permission
            # on normal run completion. Local Stop uses local_stop instead.
            await self.stop_workers()
            return {"stopped": True}
        self.state.check()
        hello = self.hello()
        if not hello.ready:
            raise RuntimeError(hello.reason)
        self.desktop.scope = self.scope
        revision = self.state.revision

        def preflight():
            self.state.check()
            if self.state.revision != revision or not self.hello().ready:
                raise RuntimeError("Local permission or Windows session changed")

        if method in {"observe", "capture"}:
            result = await self.desktop.call(method, preflight=preflight)
        elif method == "planner":
            self.automating = True
            result = await self.planner.call(method, arguments, preflight=preflight)
        else:
            raise ValueError("Unknown companion operation")
        self.state.check()
        if revision != self.state.revision:
            raise RuntimeError("Sharing changed; observation discarded")
        return result

    async def execute(self, arguments):
        try:
            revision = self.state.check(write=True)
            hello = self.hello()
            if not hello.ready:
                raise RuntimeError(hello.reason)
            permit = Permit.model_validate(arguments)
            permit.verify(self.credentials["token"], self.epoch, revision)
            old = self.journal.claim(permit)
        except Exception as exc:
            # No worker has been called and no input can have been sent.
            return ActionNotDispatched(str(exc)).result()
        if old is not None:
            return old
        self.desktop.scope = self.scope

        def preflight():
            try:
                self.state.check(write=True)
                if revision != self.state.revision or not self.hello().ready:
                    raise RuntimeError("Local permission or Windows session changed")
                if time.time() > permit.expires_at:
                    raise ActionNotDispatched("Execution permit expired", "permit_expired")
                permit.verify(self.credentials["token"], self.epoch, self.state.revision)
            except ActionNotDispatched:
                raise
            except Exception as exc:
                raise ActionNotDispatched(str(exc)) from exc

        try:
            result = await self.desktop.call(
                "execute", permit.action.model_dump(), preflight=preflight,
                expires_at=permit.expires_at,
            )
        except ActionNotDispatched as exc:
            result = exc.result()
        except WorkerStopped as exc:
            result = uncertain_result(exc) if exc.dispatched else ActionNotDispatched(str(exc)).result()
        except Exception as exc:
            result = uncertain_result(exc)
        except BaseException:
            self.state.stop("Action outcome unknown; inspect the application before resuming")
            raise
        if result.get("outcome_unknown"):
            self.state.stop(result["text"][:300])
        self.journal.finish(permit.action_id, result)
        return result

    async def run(self):
        from websockets.asyncio.client import connect

        base = self.credentials["backend"].rstrip("/")
        url = (
            "wss://" + base[8:] if base.startswith("https://") else "ws://" + base[7:]
        ) + "/api/computer-agents/connect"
        while self.running:
            try:
                async with connect(
                    url,
                    additional_headers={
                        "Authorization": "Bearer " + self.credentials["token"]
                    },
                    max_size=MAX_FRAME,
                    open_timeout=10,
                ) as ws:
                    self.epoch = uuid.uuid4().hex
                    await ws.send(self.hello().model_dump_json())
                    self.state.last_contact = time.monotonic()
                    self.status = "Connected"
                    send_lock = asyncio.Lock()
                    mutation_lock = asyncio.Lock()

                    async def heartbeat():
                        while True:
                            h = self.hello()
                            if not h.ready and self.state.armed:
                                await self.local_stop(h.reason)
                            if time.monotonic() - self.state.last_contact > 15:
                                await self.local_stop("Backend connection lost")
                                await ws.close()
                                return
                            async with send_lock:
                                await ws.send(
                                    packed(
                                        {
                                            "type": "status",
                                            "state": self.hello().model_dump(),
                                        }
                                    )
                                )
                            await asyncio.sleep(1)

                    timer = asyncio.create_task(heartbeat())
                    try:
                        async for raw in ws:
                            self.state.last_contact = time.monotonic()
                            message = json.loads(raw)
                            if message.get("type") == "heartbeat":
                                continue
                            if len(self.tasks) >= 8:
                                raise RuntimeError("Companion request queue full")
                            task = asyncio.create_task(
                                self.handle(message, ws, send_lock, mutation_lock)
                            )
                            self.tasks.add(task)

                            def finished(done):
                                self.tasks.discard(done)
                                if not done.cancelled():
                                    done.exception()

                            task.add_done_callback(finished)
                    finally:
                        timer.cancel()
                        for task in list(self.tasks):
                            task.cancel()
                        await asyncio.gather(timer, *self.tasks, return_exceptions=True)
            except Exception:
                self.status = "Disconnected; reconnecting"
            finally:
                await self.local_stop(
                    "Connection ended; enable control again after reconnecting"
                )
            if self.running:
                await asyncio.sleep(3)

    async def handle(self, message, ws, send_lock, mutation_lock):
        failed = False
        try:
            if message.get("method") == "execute":
                async with mutation_lock:
                    result = await self.dispatch(message)
            else:
                result = await self.dispatch(message)
            reply = {"id": message["id"], "result": result}
        except Exception as exc:
            failed = True
            reply = {"id": message.get("id"), "error": str(exc)[:500]}
        async with send_lock:
            if failed:
                # A local stop can interrupt an RPC before the next heartbeat.
                # Deliver its state first so the backend pauses the run before
                # interpreting the interrupted response as an execution failure.
                await ws.send(
                    packed({"type": "status", "state": self.hello().model_dump()})
                )
            await ws.send(packed(reply))
