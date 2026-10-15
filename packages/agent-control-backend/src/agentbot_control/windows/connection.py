from __future__ import annotations

import asyncio
import time
import uuid

from agentbot.interfaces import (
    SandboxError,
)

from agentbot_control.schemas import Conflict


class Connection:
    def __init__(self, ws, token, hello):
        self.ws, self.token, self.hello = ws, token, hello
        self.pending = {}
        self.send_lock = asyncio.Lock()
        self.last_seen = time.monotonic()
        self.closed = False

    def check(self, write=False):
        h = self.hello
        if self.closed or time.monotonic() - self.last_seen > 12:
            raise Conflict("Windows companion is disconnected", code="computer_unavailable")
        if not h.ready or not h.sharing or (write and not h.armed):
            raise Conflict(h.reason or "Enable sharing and control in the Windows companion")

    async def rpc(self, method, arguments=None, timeout=25):
        if self.closed:
            raise SandboxError("Windows companion disconnected")
        if len(self.pending) >= 8:
            raise Conflict("Windows companion is busy", code="computer_unavailable")
        rid = uuid.uuid4().hex
        future = asyncio.get_running_loop().create_future()
        self.pending[rid] = future
        try:
            async with self.send_lock:
                await asyncio.wait_for(
                    self.ws.send_json({"id": rid, "method": method, "arguments": arguments or {}}),
                    5,
                )
            result = await asyncio.wait_for(asyncio.shield(future), timeout)
            if result.get("error"):
                raise SandboxError(result["error"][:500])
            return result.get("result")
        finally:
            self.pending.pop(rid, None)
            if not future.done():
                future.cancel()

    def disconnect(self):
        self.closed = True
        for future in self.pending.values():
            if not future.done():
                future.set_exception(SandboxError("Windows companion connection lost"))
