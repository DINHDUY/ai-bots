"""In-memory sandbox used by unit tests."""

from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any

from agentbot.interfaces import (
    CommandResult,
    DesktopResult,
    ISandboxClient,
    SandboxError,
)
from agentbot.sandbox.paths import resolve_workspace_path, validate_http_url


class FakeSandbox(ISandboxClient):
    def __init__(self) -> None:
        self.files: dict[str, str] = {}
        self.commands: list[str] = []
        self.actions: list[tuple[str, dict[str, Any]]] = []
        self.clicks: list[str] = []
        self.opened: list[str] = []
        self.fail_actions: set[str] = set()
        self.closed = False

    async def run_bash(self, command: str) -> str:
        self.commands.append(command)
        return f"stdout: {command}"

    async def run_command(self, command: str) -> CommandResult:
        return CommandResult(uuid.uuid4().hex, 0, stdout=await self.run_bash(command))

    async def run_command_checked(
        self, command: str, *, expected: str
    ) -> CommandResult:
        if expected != await self.workspace_revision():
            raise SandboxError("Workspace revision changed")
        return await self.run_command(command)

    async def workspace_revision(self) -> str:
        return hashlib.sha256(
            json.dumps(self.files, sort_keys=True).encode()
        ).hexdigest()

    async def file_revision(self, path: str) -> str:
        value = self.files.get(resolve_workspace_path(path))
        return (
            hashlib.sha256(value.encode()).hexdigest()
            if value is not None
            else "missing"
        )

    async def write_workspace_file_checked(
        self, path: str, content: str, *, expected: str
    ) -> None:
        if expected != await self.file_revision(path):
            raise SandboxError("File revision changed")
        await self.write_workspace_file(path, content)

    async def browser_open_scoped(self, url: str, *, expected: str) -> bytes:
        return await self.browser_open(url)

    async def browser_click(self, selector: str) -> bytes:
        self.clicks.append(selector)
        return b"\x89PNG\r\n"

    async def browser_open(self, url: str) -> bytes:
        validate_http_url(url)
        self.opened.append(url)
        return b"\x89PNG\r\n"

    async def write_workspace_file(self, path: str, content: str) -> None:
        self.files[resolve_workspace_path(path)] = content

    async def read_workspace_file(self, path: str) -> str:
        key = resolve_workspace_path(path)
        if key not in self.files:
            raise SandboxError(f"No such file: {key}")
        return self.files[key]

    async def list_workspace(self, path: str) -> str:
        root = resolve_workspace_path(path, allow_root=True).rstrip("/") + "/"
        names: set[str] = set()
        for key in self.files:
            if key.startswith(root):
                names.add(key[len(root) :].split("/", 1)[0])
        return "\n".join(sorted(names))

    async def workspace_kind(self, path: str) -> str:
        target = resolve_workspace_path(path, allow_root=True)
        if target in self.files:
            return "file"
        prefix = target.rstrip("/") + "/"
        if target == "/workspace" or any(key.startswith(prefix) for key in self.files):
            return "dir"
        return "missing"

    async def screenshot(self) -> bytes:
        result = await self.desktop_action("screenshot", {})
        assert result.image is not None
        return result.image

    async def desktop_action(self, name: str, params: dict[str, Any]) -> DesktopResult:
        self.actions.append((name, params))
        if name in self.fail_actions:
            return DesktopResult(ok=False, error=f"{name} failed")
        if name in {"screenshot", "zoom"}:
            return DesktopResult(ok=True, text="OK", image=b"\x89PNG\r\n")
        if name == "cursor_position":
            return DesktopResult(ok=True, text="X=1, Y=2")
        return DesktopResult(ok=True, text="OK")

    async def close(self) -> None:
        self.closed = True


class MemorySessions:
    def __init__(self) -> None:
        self._cache: dict[str, FakeSandbox] = {}
        self.created = 0
        self.closed: list[str] = []

    async def get_or_create(self, session_id: str) -> FakeSandbox:
        if session_id not in self._cache:
            self._cache[session_id] = FakeSandbox()
            self.created += 1
        return self._cache[session_id]

    async def close(self, session_id: str) -> None:
        self.closed.append(session_id)
        sandbox = self._cache.pop(session_id, None)
        if sandbox is not None:
            await sandbox.close()
