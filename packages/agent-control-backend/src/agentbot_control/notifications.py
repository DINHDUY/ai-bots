"""Coalesced commit notifications; durable cursors remain the source of truth."""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Generator
from contextlib import contextmanager


class CommitNotifications:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._subscribers: dict[str, set[tuple[asyncio.AbstractEventLoop, asyncio.Event]]] = {}

    @contextmanager
    def subscribe(self, bot_id: str) -> Generator[asyncio.Event, None, None]:
        subscriber = (asyncio.get_running_loop(), asyncio.Event())
        with self._lock:
            self._subscribers.setdefault(bot_id, set()).add(subscriber)
        try:
            yield subscriber[1]
        finally:
            with self._lock:
                subscribers = self._subscribers[bot_id]
                subscribers.discard(subscriber)
                if not subscribers:
                    del self._subscribers[bot_id]

    def publish(self, bot_ids: set[str]) -> None:
        with self._lock:
            subscribers = [s for bid in bot_ids for s in self._subscribers.get(bid, ())]
        for loop, event in subscribers:
            try:
                loop.call_soon_threadsafe(event.set)
            except RuntimeError:
                # Closing observers cannot undo a committed transaction.
                continue
