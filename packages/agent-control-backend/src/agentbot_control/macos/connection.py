"""Bounded RPC correlation with a paired Mac, independent of browser clients."""

import asyncio
import time
import uuid

from agentbot.interfaces import SandboxError
from agentbot_macos.protocol import Envelope, Hello

from agentbot_control.schemas import Conflict


class MacConnectionRejected(Conflict):
    """Connection rejected before claiming a binding or sending any desktop RPC."""


class Connection:
    def __init__(self, ws, token: str, hello: Hello):
        self.ws, self.token, self.hello = ws, token, hello
        self.pending = {}
        self.send_lock = asyncio.Lock()
        self.last_seen = time.monotonic()
        self.closed = False

    def check(self, write=False):
        if self.closed or time.monotonic() - self.last_seen > 12:
            raise Conflict("Mac companion is offline", code="computer_unavailable")
        if not self.hello.ready:
            raise Conflict(self.hello.reason or "Check macOS companion permissions locally")
        if not self.hello.sharing:
            raise Conflict("Select a window and enable Share screen in the macOS companion")
        if write and not self.hello.armed:
            raise Conflict("Enable Allow agent control in the macOS companion")

    async def rpc(self, method, arguments=None, timeout=30):
        if self.closed:
            raise SandboxError("Mac companion disconnected")
        if len(self.pending) >= 8:
            raise Conflict("Mac companion is busy")
        request = Envelope(
            id=uuid.uuid4().hex,
            method=method,
            arguments=arguments or {},
            deadline=time.time() + timeout,
        )
        future = asyncio.get_running_loop().create_future()
        self.pending[request.id] = future
        try:
            async with self.send_lock:
                await asyncio.wait_for(self.ws.send_json(request.model_dump()), 5)
            value = await asyncio.wait_for(asyncio.shield(future), timeout)
            if value.get("error"):
                raise SandboxError(value["error"][:500])
            return value["result"]
        finally:
            self.pending.pop(request.id, None)
            if not future.done():
                future.cancel()

    def disconnect(self):
        self.closed = True
        for future in self.pending.values():
            if not future.done():
                future.set_exception(SandboxError("Mac companion connection lost"))
