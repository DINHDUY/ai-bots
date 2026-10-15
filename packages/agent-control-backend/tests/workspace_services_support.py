import struct
import zlib

from agentbot.interfaces import CaptureImage, CaptureResult, SandboxError, utc_now
from control_support import _app
from fakes import FakeSandbox, MemorySessions


def png():
    def chunk(kind, data):
        return (
            struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
        )

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", 2, 2, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(b"\0" + bytes(6) + b"\0" + bytes(6)))
        + chunk(b"IEND", b"")
    )


class LiveSandbox(FakeSandbox):
    def __init__(self, sid):
        super().__init__()
        self.sid, self.sequence, self.epoch = sid, 0, 1
        self.inputs = []
        self.degraded = False
        self.stopped = False

    async def capture(self, surface):
        self.sequence += 1
        return CaptureImage(
            CaptureResult(
                png(),
                f"{self.sid}:{self.epoch}:{surface}",
                surface,
                2,
                2,
                utc_now(),
                self.sequence,
                f"{self.epoch}:2x2",
                url="https://example.test/?token=secret",
            )
        )

    async def human_input(self, surface, event):
        self.inputs.append((surface, event))
        return await self.capture(surface)


class LiveManager(MemorySessions):
    def configure_scope(self, namespace, deployment):
        return None

    def bind(self, sid, bot_id, generation):
        return None

    async def legacy_candidate(self, bot_id):
        return None

    async def reconcile(self, sid, uncertain):
        return (await self.inspect(sid))["lifecycle"]

    async def get_or_create(self, sid):
        if sid not in self._cache:
            self._cache[sid] = LiveSandbox(sid)
            self.created += 1
        return self._cache[sid]

    async def existing(self, sid):
        sandbox = self._cache.get(sid)
        if not sandbox or sandbox.stopped:
            raise SandboxError("Computer not running")
        return sandbox

    async def inspect(self, sid):
        sandbox = self._cache.get(sid)
        return {
            "lifecycle": "missing" if not sandbox else "exited" if sandbox.stopped else "running",
            "compatible": True,
            "started_at": "2026-10-07T00:00:00Z",
            "services": {
                "browser": bool(sandbox and not sandbox.degraded),
                "desktop": bool(sandbox),
            },
        }

    async def hibernate(self, sid):
        self._cache[sid].stopped = True

    async def resume(self, sid):
        sandbox = self._cache[sid]
        sandbox.stopped = False
        sandbox.epoch += 1
        return sandbox


def live_app(tmp_path):
    app, _, _, _ = _app(tmp_path)
    manager = LiveManager()
    app.state.kernel.sandboxes = manager
    return app, manager


def create_computer(client, bid, generation=0, request="create_computer_1"):
    response = client.post(
        f"/api/bots/{bid}/lifecycle/create",
        json={"request_id": request, "generation": generation},
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "completed", response.text
    return response.json()["computer"]
