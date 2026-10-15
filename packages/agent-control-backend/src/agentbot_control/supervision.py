"""Progress-based worker health. A live task alone is not a heartbeat."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable, Coroutine
from dataclasses import dataclass
from typing import Any


class PersistenceProbe:
    """Bound health response time without cancelling or multiplying database work."""

    def __init__(self, operation: Callable[[], Awaitable[object]], *, timeout: float = 1):
        self.operation = operation
        self.timeout = timeout
        self.task: asyncio.Task[bool] | None = None

    async def _run(self) -> bool:
        try:
            await self.operation()
            return True
        except Exception:
            return False

    async def healthy(self) -> bool:
        if self.task is None:
            self.task = asyncio.create_task(self._run())
        task = self.task
        done, _ = await asyncio.wait((task,), timeout=self.timeout)
        if not done:
            return False
        if self.task is task:
            self.task = None
        return task.result()

    async def close(self) -> None:
        if self.task is not None:
            await self.task


@dataclass
class Worker:
    task: asyncio.Task[None]
    timeout: float
    required: bool
    started: float
    progress: float | None = None


class WorkerHealth:
    def __init__(self, clock: Callable[[], float] = time.monotonic):
        self.clock = clock
        self.workers: dict[str, Worker] = {}

    def start(
        self, name: str, coroutine: Coroutine[Any, Any, None], *,
        timeout: float, required: bool = True,
    ) -> asyncio.Task[None]:
        if name in self.workers and not self.workers[name].task.done():
            coroutine.close()
            raise ValueError(f"Worker already registered: {name}")
        task = asyncio.create_task(coroutine, name=name)
        self.workers[name] = Worker(task, timeout, required, self.clock())
        # Consume the exception without logging potentially sensitive payloads.
        task.add_done_callback(lambda task: None if task.cancelled() else task.exception())
        return task

    def progressed(self, name: str) -> None:
        if worker := self.workers.get(name):
            worker.progress = self.clock()

    def snapshot(self) -> dict[str, str]:
        now = self.clock()
        result: dict[str, str] = {}
        for name, worker in self.workers.items():
            if worker.task.done():
                result[name] = "stopped"
            elif now - (worker.progress if worker.progress is not None else worker.started) > worker.timeout:
                result[name] = "stalled"
            else:
                result[name] = "healthy" if worker.progress is not None else "starting"
        return result

    def ready(self) -> bool:
        states = self.snapshot()
        return all(not worker.required or states[name] == "healthy" for name, worker in self.workers.items())

    def admitting(self) -> bool:
        """Allow the startup grace period; stop admission on terminated/stalled work."""
        states = self.snapshot()
        return all(not worker.required or states[name] in {"healthy", "starting"} for name, worker in self.workers.items())

    async def stop(self) -> None:
        for worker in self.workers.values():
            worker.task.cancel()
        await asyncio.gather(*(worker.task for worker in self.workers.values()), return_exceptions=True)
