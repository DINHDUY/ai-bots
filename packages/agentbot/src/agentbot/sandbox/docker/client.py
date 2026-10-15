from __future__ import annotations

import asyncio
import base64
import hashlib
import io
import json
import struct
import tarfile
import uuid
from typing import Any

from agentbot.interfaces import (
    CaptureImage,
    CaptureResult,
    CommandResult,
    DesktopResult,
    ISandboxClient,
    SandboxError,
    TerminationUnverified,
    utc_now,
)
from agentbot.sandbox.docker.constants import BROWSER_CTL, COMMAND_SCRIPT, DESKTOP_SCRIPT
from agentbot.sandbox.paths import resolve_workspace_path, validate_http_url


class DockerSandbox(ISandboxClient):
    """One unprivileged container with a shell, workspace, desktop, and browser."""

    def __init__(self, container: Any, session_id: str, *, command_timeout: int = 30) -> None:
        self._container = container
        self.session_id = session_id
        self.command_timeout = command_timeout
        self._commands: set[str] = set()
        self._uncertain = False
        self._capture_sequence = 0

    @property
    def uncertain(self) -> bool:
        return self._uncertain

    @property
    def uncertain_reason(self) -> str:
        return "Docker sandbox command outcome could not be verified."

    def capture_image(self, data, surface, transform=None):
        raw = base64.b64decode(data["image_b64"])
        if len(raw) < 24 or not raw.startswith(b"\x89PNG\r\n\x1a\n"):
            raise SandboxError("Invalid capture PNG")
        width, height = struct.unpack(">II", raw[16:24])
        if width > 4096 or height > 4096 or width * height > 16777216 or len(raw) > 4 * 1024 * 1024:
            raise SandboxError("Capture exceeds limits")
        self._capture_sequence += 1
        epoch = self._container.attrs.get("State", {}).get("StartedAt", "unknown")
        surface_id = (
            self.session_id + ":" + hashlib.sha256(epoch.encode()).hexdigest()[:12] + ":" + surface
        )
        meta = data.get("capture", {})
        return CaptureImage(
            CaptureResult(
                raw,
                surface_id,
                surface,
                width,
                height,
                meta.get("captured_at", utc_now()),
                self._capture_sequence,
                f"{surface_id}:{width}x{height}",
                meta.get("url"),
                meta.get("title"),
                meta.get("cursor") if not transform else None,
                transform,
            )
        )

    async def capture(self, surface="browser"):
        if surface == "browser":
            return await self._browser("capture", "")
        if surface == "desktop":
            return await self.screenshot()
        raise SandboxError("Unknown capture surface")

    async def human_input(self, surface, event):
        if surface == "browser":
            return await self._browser("input", json.dumps(event))
        if surface != "desktop":
            raise SandboxError("Unsupported input surface")
        code, stdout, stderr = await self._exec(
            ["python3", "/opt/agentbot_sandbox/input.py", json.dumps(event)]
        )
        result = json.loads(stdout)
        if code or not result.get("ok"):
            raise SandboxError(result.get("error") or stderr)
        return await self.capture("desktop")

    async def service_health(self):
        result = await asyncio.to_thread(
            self._container.exec_run, ["python3", "/opt/agentbot_sandbox/probe.py"]
        )
        if result.exit_code:
            raise SandboxError("Health probe unavailable")
        return json.loads(result.output)

    async def files(self, operation, **arguments):
        code, stdout, stderr = await self._exec(
            [
                "python3",
                "/opt/agentbot_sandbox/files.py",
                json.dumps({"operation": operation, **arguments}),
            ],
            timeout=60,
        )
        try:
            result = json.loads(stdout)
        except ValueError as exc:
            raise SandboxError(stderr or "File service unavailable") from exc
        if code or not result.get("ok"):
            raise SandboxError(result.get("error", "File operation failed"))
        return result["result"]

    async def approval_protocol(self) -> int | None:
        """Image metadata is immutable to the sandbox user; never trust a writable helper."""
        labels = self._container.attrs.get("Config", {}).get("Labels", {}) or {}
        return 2 if labels.get("agentbot.sandbox_protocol") == "2" else None

    async def terminal(self, operation, **arguments):
        code, stdout, stderr = await self._exec(
            [
                "python3",
                "/opt/agentbot_sandbox/terminalctl.py",
                json.dumps({"op": operation, **arguments}),
            ],
            timeout=10,
        )
        try:
            result = json.loads(stdout)
        except ValueError as exc:
            raise SandboxError("Terminal service unavailable") from exc
        if code or not result.get("ok"):
            raise SandboxError(result.get("error") or stderr)
        return result

    async def run_bash(self, command: str) -> str:
        return (await self.run_command(command)).text()

    async def run_command(self, command: str) -> CommandResult:
        return await self.run_command_checked(command)

    async def run_command_checked(
        self, command: str, *, expected: str | None = None
    ) -> CommandResult:
        command_id = uuid.uuid4().hex
        self._commands.add(command_id)
        try:
            args = [
                "python3",
                COMMAND_SCRIPT,
                "run",
                command_id,
                str(self.command_timeout),
                command,
            ]
            if expected:
                args.append(expected)
            code, stdout, stderr = await self._exec(args, timeout=self.command_timeout + 10)
            if code != 0:
                raise SandboxError(
                    stderr or "Sandbox command supervisor unavailable; rebuild the sandbox image."
                )
            return CommandResult(**json.loads(stdout))
        finally:
            self._commands.discard(command_id)

    async def workspace_revision(self) -> str:
        return await self._revision("workspace")

    async def file_revision(self, path: str) -> str:
        return await self._revision("file", resolve_workspace_path(path))

    async def _revision(self, operation: str, *args: str) -> str:
        code, stdout, stderr = await self._exec(
            ["python3", "/opt/agentbot_sandbox/revisions.py", operation, *args]
        )
        try:
            result = json.loads(stdout)
        except ValueError as exc:
            raise SandboxError(
                stderr or "Revision service unavailable; rebuild the sandbox image."
            ) from exc
        if code != 0 or not result.get("ok"):
            raise SandboxError(result.get("error") or stderr)
        return result["result"]

    async def cancel_commands(self) -> None:
        for command_id in list(self._commands):
            result = await asyncio.to_thread(
                self._container.exec_run,
                ["python3", COMMAND_SCRIPT, "cancel", command_id],
            )
            if result.exit_code != 0:
                self._uncertain = True
        if self._uncertain:
            raise TerminationUnverified("Sandbox command termination could not be verified.")

    async def browser_click(self, selector: str) -> bytes:
        return await self._browser("click", selector)

    async def browser_open(self, url: str) -> bytes:
        validate_http_url(url)
        return await self._browser("open", url)

    async def write_workspace_file(self, path: str, content: str) -> None:
        await self.write_workspace_file_checked(path, content)

    async def write_workspace_file_checked(
        self, path: str, content: str, *, expected: str | None = None
    ) -> None:
        data = content.encode("utf-8")
        if len(data) > 65536:
            raise SandboxError("Text writes are limited to 64 KiB")
        args = [resolve_workspace_path(path), base64.b64encode(data).decode()]
        if expected is not None:
            args.append(expected)
        await self._revision("write", *args)

    async def read_workspace_file(self, path: str) -> str:
        target = resolve_workspace_path(path)
        kind = await self.workspace_kind(path)
        if kind == "missing":
            raise SandboxError(f"No such file: {target}")
        if kind == "dir":
            raise SandboxError(f"Is a directory: {target}")

        def _read() -> bytes:
            bits, _stat = self._container.get_archive(target)
            blob = b"".join(bits)
            with tarfile.open(fileobj=io.BytesIO(blob), mode="r:") as archive:
                member = archive.next()
                if member is None:
                    raise SandboxError(f"Empty archive for {target}")
                extracted = archive.extractfile(member)
                if extracted is None:
                    raise SandboxError(f"Unreadable file: {target}")
                return extracted.read()

        try:
            data = await self._blocking(_read)
        except SandboxError:
            raise
        except Exception as exc:
            raise SandboxError(f"Failed to read {target}: {exc}") from exc
        return data.decode("utf-8", errors="replace")

    async def list_workspace(self, path: str) -> str:
        target = resolve_workspace_path(path, allow_root=True)
        code, stdout, stderr = await self._exec(["ls", "-1A", target])
        if code != 0:
            raise SandboxError(stderr or stdout or f"Cannot list {target}")
        return stdout

    async def workspace_kind(self, path: str) -> str:
        target = resolve_workspace_path(path, allow_root=True)
        code, _stdout, _stderr = await self._exec(["test", "-d", target])
        if code == 0:
            return "dir"
        code, _stdout, _stderr = await self._exec(["test", "-f", target])
        if code == 0:
            return "file"
        return "missing"

    async def screenshot(self) -> bytes:
        result = await self.desktop_action("screenshot", {})
        if not result.ok or result.image is None:
            raise SandboxError(result.error or "Screenshot failed.")
        return result.image

    async def desktop_action(self, name: str, params: dict[str, Any]) -> DesktopResult:
        code, stdout, stderr = await self._exec(
            ["python3", DESKTOP_SCRIPT, name, json.dumps(params)],
            timeout=90,
        )
        if not stdout:
            return DesktopResult(ok=False, error=stderr or f"desktop action exited {code}")
        try:
            data = json.loads(stdout)
        except json.JSONDecodeError:
            return DesktopResult(ok=False, error=stderr or stdout[:500])
        transform = (
            {"kind": "crop", "region": params.get("region"), "view_only": True}
            if name == "zoom"
            else None
        )
        image = self.capture_image(data, "desktop", transform) if data.get("image_b64") else None
        if not data.get("ok"):
            return DesktopResult(
                ok=False,
                error=str(data.get("error") or "desktop action failed"),
                image=image,
            )
        return DesktopResult(ok=True, text=str(data.get("text") or "OK"), image=image)

    async def close(self) -> None:
        await self._blocking(self._container.remove, force=True)

    async def _blocking(self, function, *args, **kwargs):
        work = asyncio.create_task(asyncio.to_thread(function, *args, **kwargs))
        try:
            try:
                return await asyncio.shield(work)
            except asyncio.CancelledError:
                await asyncio.shield(work)
                raise
        except Exception:
            self._uncertain = True
            raise

    async def browser_open_scoped(self, url: str, *, expected: str) -> bytes:
        validate_http_url(url)
        return await self._browser("open", url, expected)

    async def _browser(self, command: str, argument: str, origin: str | None = None) -> bytes:
        args = ["python3", BROWSER_CTL, command, argument]
        if origin:
            args.append(origin)
        code, stdout, stderr = await self._exec(args, timeout=45)
        if not stdout:
            raise SandboxError(stderr or f"browser {command} exited {code}")
        try:
            data = json.loads(stdout)
        except json.JSONDecodeError as exc:
            raise SandboxError(stderr or stdout[:500]) from exc
        if not data.get("ok"):
            raise SandboxError(str(data.get("error") or f"browser {command} failed"))
        return self.capture_image(data, "browser")

    async def _exec(self, args: list[str], timeout: int = 30) -> tuple[int, str, str]:
        def _run() -> tuple[int, str, str]:
            result = self._container.exec_run(
                args,
                demux=True,
                environment={"DISPLAY": ":99", "HOME": "/home/agent"},
            )
            stdout, stderr = (
                result.output if isinstance(result.output, tuple) else (result.output, b"")
            )
            return (
                int(result.exit_code or 0),
                (stdout or b"").decode("utf-8", errors="replace"),
                (stderr or b"").decode("utf-8", errors="replace"),
            )

        work = asyncio.create_task(asyncio.to_thread(_run))
        try:
            try:
                return await asyncio.wait_for(asyncio.shield(work), timeout=timeout)
            except (TimeoutError, asyncio.CancelledError):
                # A host timeout is not proof that an exec stopped. Drain the SDK call.
                await self.cancel_commands()
                result = await asyncio.shield(work)
                if asyncio.current_task().cancelling():
                    raise asyncio.CancelledError()
                return result
        except Exception:
            self._uncertain = True
            raise
