import asyncio
import base64
import time
import uuid

import pytest
from agentbot.interfaces import (
    CaptureImage,
    CaptureResult,
    CommandResult,
    DesktopResult,
    SandboxError,
    TerminationUnverified,
)
from agentbot.sandbox.bridge import (
    MAX_FRAME,
    Assembly,
    HostRequest,
    decode,
    encode,
    frames,
)
from agentbot.sandbox.remote import RemoteSandbox
from agentbot_computer_agent.host import Host


def config():
    return {
        "token": "machine-secret",
        "binding_id": "binding-123",
        "deployment": "deployment",
        "profile": {
            "session_id": "session-123",
            "generation": 1,
            "bot_id": "bot-123",
            "image": "sandbox@sha256:" + "a" * 64,
            "workspace_root": "/var/lib/agentbot/workspaces",
            "storage_ref": "binding-123",
            "memory_mb": 2048,
            "cpu_count": 1,
            "resource_id": "resource",
        },
    }


def request(host, method="run_command_checked", action_id=None, arguments=None):
    return HostRequest(
        id=uuid.uuid4().hex,
        action_id=action_id or uuid.uuid4().hex,
        binding_id=host.config["binding_id"],
        deployment=host.config["deployment"],
        boot_id=host.boot,
        epoch=host.epoch,
        session_id=host.config["profile"]["session_id"],
        generation=host.config["profile"]["generation"],
        deadline=float(time.time() + 60),
        method=method,
        arguments=arguments or {"command": "echo hello"},
    ).sign(host.config["token"])


class Manager:
    def __init__(self):
        self.commands, self.stopped = 0, 0

    async def existing(self, sid):
        return self

    async def run_command_checked(self, command):
        self.commands += 1
        return CommandResult("cmd", 0, stdout="hello")

    async def fence(self):
        self.stopped += 1


@pytest.mark.asyncio
async def test_durable_receipt_deduplicates_and_unknown_never_replays(tmp_path):
    manager = Manager()
    host = Host(config(), tmp_path / "host.json", manager)
    host.epoch, host.leased = 1, True
    command = request(host)
    result = await host.execute(command.model_dump())
    assert decode(result).stdout == "hello"
    assert await host.execute(command.model_dump()) == result
    assert manager.commands == 1
    host.db.execute("UPDATE receipts SET state='started',result=NULL")
    host.db.commit()
    host.db.close()
    restarted = Host(config(), tmp_path / "host.json", manager)
    restarted.epoch, restarted.leased = 1, True
    with pytest.raises(TerminationUnverified, match="not be replayed"):
        await restarted.execute(command.model_dump())
    assert manager.commands == 1
    restarted.db.close()


@pytest.mark.asyncio
async def test_signature_epoch_deadline_generation_and_lease_fence_before_dispatch(
    tmp_path,
):
    manager = Manager()
    host = Host(config(), tmp_path / "host.json", manager)
    host.epoch, host.leased = 1, True
    for change in (
        {"epoch": 2},
        {"boot_id": "different-boot"},
        {"generation": 2},
        {"deadline": float(time.time() - 1)},
    ):
        command = request(host).model_copy(update=change).sign(host.config["token"])
        with pytest.raises((ValueError, SandboxError)):
            await host.execute(command.model_dump())
    command = request(host).sign("wrong-secret")
    with pytest.raises(ValueError):
        await host.execute(command.model_dump())
    host.leased = False
    with pytest.raises(SandboxError, match="lease expired"):
        await host.execute(request(host).model_dump())
    assert manager.commands == 0
    host.db.close()


def test_chunked_binary_and_capture_provenance_round_trip_and_limits():
    capture = CaptureImage(
        CaptureResult(
            b"png", "surface", "desktop", 2, 2, "now", 5, "revision", action_id="action"
        )
    )
    value = {
        "id": "message-123",
        "result": encode(
            {
                "bytes": bytes(range(256)) * 4096,
                "desktop": DesktopResult(True, image=capture),
            }
        ),
    }
    chunks = list(frames(value))
    assert len(chunks) > 1 and all(len(c.encode()) <= MAX_FRAME for c in chunks)
    assembly = Assembly()
    for chunk in chunks:
        restored = assembly.receive(chunk)
    decoded = decode(restored["result"])
    assert decoded["bytes"] == bytes(range(256)) * 4096
    assert decoded["desktop"].image.metadata["action_id"] == "action"
    with pytest.raises(ValueError):
        Assembly().receive(chunks[1])
    with pytest.raises(ValueError):
        Assembly().receive("x" * (MAX_FRAME + 1))
    with pytest.raises(ValueError):
        Assembly().receive("[]")


@pytest.mark.docker
@pytest.mark.asyncio
async def test_real_docker_remote_contract(tmp_path):
    """Actual sandbox helpers behind the host protocol; no Azure account required."""
    from agentbot.sandbox.docker import DockerSessionManager

    import docker

    manager = DockerSessionManager(client=docker.from_env())
    sid = "remote" + uuid.uuid4().hex[:12]
    c = config()
    c["profile"]["session_id"] = sid
    host = Host(c, tmp_path / "host.json", manager)
    host.epoch, host.leased = 1, True

    async def fence():
        await manager.hibernate(sid)

    manager.fence = fence
    sandbox = await manager.get_or_create(sid)
    binding = {"session_id": sid, "provider": "azure_ml_compute_instance"}

    async def call(binding, method, arguments, action_id):
        command = request(host, method, action_id, arguments)
        command.arguments = arguments
        command.sign(c["token"])
        assembly = Assembly()
        for frame in frames(command.model_dump()):
            received = assembly.receive(frame)
        value = await host.execute(received)
        for frame in frames({"id": command.id, "result": value}):
            response = assembly.receive(frame)
        return decode(response["result"])

    remote = RemoteSandbox(binding, call)
    try:
        result = await remote.run_command("printf out; printf err >&2; exit 7")
        assert (
            result.exit_code == 7 and result.stdout == "out" and result.stderr == "err"
        )
        revision = await remote.file_revision("hello.txt")
        await remote.write_workspace_file_checked(
            "hello.txt", "hello ☁", expected=revision
        )
        assert await remote.read_workspace_file("hello.txt") == "hello ☁"
        assert await remote.file_revision("hello.txt") != revision
        snapshot = await remote.files("snapshot", path="/workspace/hello.txt")
        data = await remote.files("read", token=snapshot["token"], offset=0)
        assert base64.b64decode(data["data"]).decode() == "hello ☁"
        upload = await remote.files(
            "upload_begin", path="/workspace/binary.bin", expected_revision="missing"
        )
        raw = bytes(range(256))
        await remote.files(
            "upload_chunk",
            token=upload["token"],
            offset=0,
            data=base64.b64encode(raw).decode(),
        )
        # File service's commit revision is the upload's content SHA256.
        import hashlib

        await remote.files(
            "upload_commit",
            token=upload["token"],
            revision=hashlib.sha256(raw).hexdigest(),
        )
        for surface in ("browser", "desktop"):
            image = await remote.capture(surface)
            assert (
                image.startswith(b"\x89PNG")
                and image.metadata["surface_kind"] == surface
            )
        await remote.write_workspace_file(
            "index.html",
            '<button id="target" onclick="this.textContent=\'Clicked\'">Click me</button>',
        )
        # Fixture server: normal command helpers correctly reap their descendants.
        await asyncio.to_thread(
            sandbox._container.exec_run,
            ["python3", "-m", "http.server", "8765", "--bind", "127.0.0.1"],
            detach=True,
        )
        await asyncio.sleep(0.3)
        opened = await remote.browser_open("http://127.0.0.1:8765")
        assert opened.metadata["surface_kind"] == "browser"
        clicked = await remote.browser_click("#target")
        assert clicked.startswith(b"\x89PNG")
        await remote.human_input("desktop", {"kind": "move", "x": 2, "y": 2})
        terminal = await remote.terminal("open", id="terminal123", rows=24, cols=80)
        await remote.terminal("resize", id=terminal["id"], rows=30, cols=100)
        await remote.terminal(
            "write",
            id=terminal["id"],
            data=base64.b64encode(b"printf remote-pty\\n\n").decode(),
        )
        await asyncio.sleep(0.5)
        output = await remote.terminal("read", id=terminal["id"], offset=0)
        assert (
            "offset" in output
            and "gap" in output
            and b"remote-pty" in base64.b64decode(output["data"])
        )
        await remote.terminal("close", id=terminal["id"])
        running = asyncio.create_task(remote.run_command("sleep 20"))
        await asyncio.sleep(0.5)
        await remote.cancel_commands()
        assert (await running).cancelled
        with pytest.raises(TerminationUnverified):
            await remote.write_workspace_file("../outside", "must not escape")
    finally:
        await manager.close(sid)
        host.db.close()
