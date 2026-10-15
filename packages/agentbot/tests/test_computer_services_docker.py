import asyncio
import base64
import hashlib
import uuid

import pytest
from agentbot.interfaces import SandboxError
from agentbot.sandbox.docker import DockerSessionManager

pytestmark = pytest.mark.docker


async def test_native_files_health_surfaces_and_hibernation():
    docker = pytest.importorskip("docker")
    manager = DockerSessionManager(client=docker.from_env())
    sid = "computer" + uuid.uuid4().hex[:8]
    sandbox = await manager.get_or_create(sid)
    try:
        health = await manager.inspect(sid)
        assert (
            health["services"]["browser"]
            and health["services"]["desktop"]
            and health["services"]["terminal"]
        )
        browser, desktop = (
            await sandbox.capture("browser"),
            await sandbox.capture("desktop"),
        )
        assert browser.metadata["surface_kind"] == "browser"
        assert desktop.metadata["surface_kind"] == "desktop"
        assert desktop.metadata["surface_id"] != browser.metadata["surface_id"]
        assert desktop.metadata["cursor"] is not None
        assert browser.metadata["width"] == 1024 and desktop.metadata["height"] == 768
        moved = await sandbox.human_input("desktop", {"kind": "move", "x": 321, "y": 222})
        assert moved.metadata["cursor"]["x"] == 321
        assert moved.metadata["cursor"]["y"] == 222
        await sandbox.human_input("browser", {"kind": "down", "x": 40, "y": 50, "button": "left"})
        await sandbox.human_input("browser", {"kind": "key_down", "key": "Shift"})
        released = await sandbox.human_input("browser", {"kind": "release", "keys": ["Shift"]})
        assert released.metadata["surface_kind"] == "browser"
        await sandbox.run_command(
            'python3 -c \'from pathlib import Path; Path("binary.dat").write_bytes(bytes(range(256))*1000); Path("table.csv").write_text("a,b\\n1,2\\n"); Path(".env").write_text("TOKEN=secret"); [Path(f"item{i:03}.txt").touch() for i in range(210)]\''
        )
        listing = await sandbox.files("list", path="/workspace")
        assert len(listing["entries"]) == 200 and listing["cursor"]
        preview = await sandbox.files("preview", path="/workspace/binary.dat")
        assert preview["truncated"] and preview["returned_bytes"] == 65536
        snap = await sandbox.files(
            "snapshot", path="/workspace/binary.dat", revision=preview["revision"]
        )
        data = bytearray()
        while len(data) < snap["size"]:
            chunk = await sandbox.files("read", token=snap["token"], offset=len(data))
            data.extend(base64.b64decode(chunk["data"]))
        await sandbox.files("drop", token=snap["token"])
        assert data == bytes(range(256)) * 1000
        assert hashlib.sha256(data).hexdigest() == preview["revision"]
        await sandbox.run_command(
            "printf changed > binary.dat; ln -s /tmp escape; ln -s table.csv link.csv; mkfifo pipe"
        )
        with pytest.raises(SandboxError, match="revision"):
            await sandbox.files(
                "snapshot", path="/workspace/binary.dat", revision=preview["revision"]
            )
        protected = await sandbox.files("preview", path="/workspace/.env")
        assert protected["protected"] and "secret" not in str(protected)
        for path in (
            "/etc/passwd",
            "/workspace/../etc/passwd",
            "/workspace/escape/file",
            "/workspace/link.csv",
            "/workspace/pipe",
            "/workspace/.env",
            "..\\etc\\passwd",
        ):
            with pytest.raises(SandboxError):
                await sandbox.files("snapshot", path=path)
        stage = await sandbox.files(
            "upload_begin", path="/workspace/upload.bin", expected_revision="missing"
        )
        await sandbox.files(
            "upload_chunk",
            token=stage["token"],
            offset=0,
            data=base64.b64encode(b"complete\x00binary").decode(),
        )
        await sandbox.files(
            "upload_commit",
            token=stage["token"],
            revision=hashlib.sha256(b"complete\x00binary").hexdigest(),
        )
        stale = await sandbox.files(
            "upload_begin", path="/workspace/upload.bin", expected_revision="missing"
        )
        with pytest.raises(SandboxError, match="revision"):
            await sandbox.files(
                "upload_commit",
                token=stale["token"],
                revision=hashlib.sha256(b"").hexdigest(),
            )
        await sandbox.files("drop", token=stale["token"])
        await asyncio.sleep(2.5)
        changes = await sandbox.files("changes")
        assert changes["sequence"] > 1 and changes["rescan"]
        old_surface = browser.metadata["surface_id"]
        await manager.hibernate(sid)
        assert (await manager.inspect(sid))["lifecycle"] == "exited"
        with pytest.raises(SandboxError):
            await manager.existing(sid)
        sandbox = await manager.resume(sid)
        assert await sandbox.file_revision("table.csv") != "missing"
        assert (await sandbox.capture("browser")).metadata["surface_id"] != old_surface
        # Kill only the browser daemon, leaving its container and desktop alive.
        await sandbox._exec(
            [
                "python3",
                "-c",
                "import os,signal; from pathlib import Path; [os.kill(int(p.parent.name),signal.SIGKILL) for p in Path('/proc').glob('[0-9]*/cmdline') if b'/opt/agentbot_sandbox/browserd.py' in p.read_bytes().split(b'\\0')]",
            ]
        )
        await asyncio.sleep(0.2)
        health = await manager.inspect(sid)
        assert (
            health["lifecycle"] == "running"
            and not health["services"]["browser"]
            and health["services"]["desktop"]
        )
    finally:
        await manager.close(sid)


async def test_pty_replay_resize_interrupt_background_cleanup():
    docker = pytest.importorskip("docker")
    manager = DockerSessionManager(client=docker.from_env())
    sid = "pty" + uuid.uuid4().hex[:8]
    sandbox = await manager.get_or_create(sid)
    try:
        terminal = await sandbox.terminal("open", rows=24, cols=80)
        tid = terminal["id"]

        async def write(text):
            return await sandbox.terminal(
                "write", id=tid, data=base64.b64encode(text.encode()).decode()
            )

        async def read_until(expected):
            for _ in range(30):
                result = await sandbox.terminal("read", id=tid, offset=0)
                if expected in base64.b64decode(result["data"]):
                    return result
                await asyncio.sleep(0.1)
            pytest.fail("PTY output did not arrive")

        await sandbox.terminal("resize", id=tid, rows=33, cols=90)
        await write("stty size\n")
        await read_until(b"33 90")
        await write("printf '\\303\\251\\360\\237\\231\\202\\n'\n")
        await read_until("é🙂".encode())
        await write("python3 -c 'print(\"z\" * 400000)'\n")
        await asyncio.sleep(1)
        result = await sandbox.terminal("read", id=tid, offset=0)
        assert result["gap"] and result["floor"] > 0
        assert len(base64.b64decode(result["data"])) <= 16384
        await write("sleep 120 & echo $! > /workspace/background.pid; sleep 120\n")
        await asyncio.sleep(0.3)
        await sandbox.terminal("signal", id=tid, signal="INT")
        await write("echo interrupt_ok > /workspace/interrupted\n")
        await asyncio.sleep(0.3)
        assert await sandbox.file_revision("interrupted") != "missing"
        await sandbox.terminal("close", id=tid)
        assert (
            await sandbox.run_command("kill -0 $(cat background.pid) 2>/dev/null")
        ).exit_code != 0
        assert (await sandbox.terminal("close", id=tid))["closed"]
        with pytest.raises(SandboxError):
            await sandbox.terminal("write", id=tid, data="eA==")
    finally:
        await manager.close(sid)
