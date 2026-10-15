import asyncio
import os
import uuid

import pytest

pytestmark = pytest.mark.docker


async def test_structured_outcomes_and_checked_revisions():
    docker = pytest.importorskip("docker")
    from agentbot.interfaces import SandboxError
    from agentbot.sandbox.docker import DockerSessionManager

    manager = DockerSessionManager(client=docker.from_env())
    sid = "outcomes" + uuid.uuid4().hex[:8]
    sandbox = await manager.get_or_create(sid)
    try:
        result = await sandbox.run_command("printf out; printf err >&2; exit 124")
        assert result.exit_code == 124 and not result.timed_out and not result.cancelled
        assert result.stdout == "out" and result.stderr == "err"
        assert result.command_id and result.started_at <= result.ended_at
        result = await sandbox.run_command("python3 -c 'print(\"x\" * 20000)'")
        assert result.ok and result.stdout_truncated and len(result.stdout) == 16000
        sandbox.command_timeout = 0.15
        result = await sandbox.run_command("exec 1>&- 2>&-; sleep 4; touch late")
        assert result.timed_out and not result.cancelled
        assert await sandbox.workspace_kind("late") == "missing"
        sandbox.command_timeout = 30
        await sandbox.write_workspace_file("script.sh", "echo old")
        revision = await sandbox.workspace_revision()
        await sandbox.write_workspace_file("script.sh", "echo new")
        with pytest.raises(SandboxError, match="revision changed"):
            await sandbox.run_command_checked("bash script.sh", expected=revision)
        before = await sandbox.file_revision("script.sh")
        await sandbox.write_workspace_file_checked(
            "script.sh", "echo newest", expected=before
        )
        with pytest.raises(SandboxError, match="revision changed"):
            await sandbox.write_workspace_file_checked(
                "script.sh", "overwrite", expected=before
            )
        await sandbox.run_command("ln -s /tmp escaped")
        with pytest.raises(SandboxError):
            await sandbox.write_workspace_file("escaped/should-not-exist", "outside")
        with pytest.raises(SandboxError):
            await sandbox.workspace_revision()
        protected_helper = await sandbox.run_command(
            "test -w /opt/agentbot_sandbox/command.py"
        )
        assert protected_helper.exit_code == 1
    finally:
        await manager.close(sid)


async def test_browser_origin_rule_blocks_redirect_before_target_request():
    docker = pytest.importorskip("docker")
    from agentbot.interfaces import SandboxError
    from agentbot.sandbox.docker import DockerSessionManager

    manager = DockerSessionManager(client=docker.from_env())
    sid = "origins" + uuid.uuid4().hex[:8]
    sandbox = await manager.get_or_create(sid)
    try:
        server = """
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path in ('/chain', '/same'):
            self.send_response(302)
            self.send_header('Location', '/redirect' if self.path == '/chain' else '/')
            self.end_headers()
        elif self.path == '/redirect':
            self.send_response(302)
            self.send_header('Location', 'http://localhost:8765/target')
            self.end_headers()
        else:
            if self.path == '/target':
                Path('/workspace/target-visited').write_text('visited')
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'<html><body>Local page</body></html>')
HTTPServer(('0.0.0.0', 8765), Handler).serve_forever()
"""
        await asyncio.to_thread(
            sandbox._container.exec_run, ["python3", "-c", server], detach=True
        )
        for _ in range(100):
            code, _, _ = await sandbox._exec(
                ["test", "-S", "/tmp/agentbot-browser.sock"]
            )
            if code == 0:
                break
            await asyncio.sleep(0.05)
        else:
            pytest.fail("Browser test fixture did not become ready")
        image = await sandbox.browser_open_scoped(
            "http://127.0.0.1:8765/", expected="http://127.0.0.1:8765"
        )
        assert image.startswith(b"\x89PNG")
        assert (
            await sandbox.browser_open_scoped(
                "http://127.0.0.1:8765/same", expected="http://127.0.0.1:8765"
            )
        ).startswith(b"\x89PNG")
        with pytest.raises(SandboxError):
            await sandbox.browser_open_scoped(
                "http://127.0.0.1:8765/redirect", expected="http://127.0.0.1:8765"
            )
        with pytest.raises(SandboxError):
            await sandbox.browser_open_scoped(
                "http://127.0.0.1:8765/chain", expected="http://127.0.0.1:8765"
            )
        assert await sandbox.workspace_kind("target-visited") == "missing"
    finally:
        await manager.close(sid)


async def test_docker_bash_files_and_screenshot() -> None:
    docker = pytest.importorskip("docker")
    try:
        client = docker.from_env()
        client.ping()
        client.images.get(os.getenv("SANDBOX_IMAGE", "agentbot-sandbox"))
    except Exception as exc:
        pytest.skip(f"agentbot-sandbox is not available: {exc}")

    from agentbot.sandbox.docker import DockerSessionManager
    from agentbot.sandbox.paths import WorkspacePathError

    session_id = f"pytest{uuid.uuid4().hex[:8]}"
    manager = DockerSessionManager(client=client)
    sandbox = await manager.get_or_create(session_id)
    try:
        output = await sandbox.run_bash("echo hello-sandbox")
        assert "hello-sandbox" in output
        await sandbox.write_workspace_file("note.txt", "hi")
        assert await sandbox.read_workspace_file("note.txt") == "hi"
        with pytest.raises(WorkspacePathError):
            await sandbox.write_workspace_file("/etc/passwd", "x")
        image = await sandbox.screenshot()
        assert image.startswith(b"\x89PNG")
    finally:
        await manager.close(session_id)


async def test_supervised_command_cancellation_prevents_late_writes():
    docker = pytest.importorskip("docker")
    client = docker.from_env()
    client.ping()
    client.images.get(os.getenv("SANDBOX_IMAGE", "agentbot-sandbox"))
    from agentbot.sandbox.docker import DockerSessionManager

    sid = "cancel" + uuid.uuid4().hex[:8]
    manager = DockerSessionManager(client=client)
    sandbox = await manager.get_or_create(sid)
    try:
        task = asyncio.create_task(
            sandbox.run_bash("touch /workspace/started; sleep 3; touch /workspace/late")
        )
        for _ in range(100):
            if await sandbox.workspace_kind("started") == "file":
                break
            await asyncio.sleep(0.02)
        else:
            pytest.fail("Command never started")
        await sandbox.cancel_commands()
        await task
        await asyncio.sleep(3.1)
        assert await sandbox.workspace_kind("late") == "missing"
        assert "alive" in await sandbox.run_bash("echo alive")
        inspector = DockerSessionManager(client=client)
        inspector.configure_scope("control", "test")
        assert await inspector.reconcile(sid, False) == "missing"
    finally:
        await manager.close(sid)
