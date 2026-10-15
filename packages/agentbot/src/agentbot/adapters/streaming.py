"""Short, lossless batches of model text with explicit event boundaries."""

import asyncio


class TextBatcher:
    def __init__(self, emit, *, interval=0.075, max_chars=4000):
        self.emit, self.interval, self.max_chars = emit, interval, max_chars
        self.parts = []
        self.size = 0
        self.timer = None

    async def append(self, text):
        # Keep each persisted payload below the event store's truncation limit.
        while text:
            piece, text = (
                text[: self.max_chars - self.size],
                text[self.max_chars - self.size :],
            )
            self.parts.append(piece)
            self.size += len(piece)
            if self.size >= self.max_chars:
                await self.flush()
        if self.parts and self.timer is None:
            self.timer = asyncio.create_task(self._later())

    async def _later(self):
        try:
            await asyncio.sleep(self.interval)
            await self.flush()
        except asyncio.CancelledError:
            pass

    async def flush(self):
        timer, self.timer = self.timer, None
        if timer is not None and timer is not asyncio.current_task():
            timer.cancel()
            # No await here: flush must enqueue before a concurrent tool boundary.
        if self.parts:
            text = "".join(self.parts)
            self.parts, self.size = [], 0
            await self.emit(text)
