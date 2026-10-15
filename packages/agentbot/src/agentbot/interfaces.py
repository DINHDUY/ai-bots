"""Structural boundaries between the kernel, sandboxes, and framework adapters."""

from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol, runtime_checkable

from agentbot.models import ModelConfig


class SandboxError(Exception):
    """The isolated environment failed to carry out a request."""


@dataclass(frozen=True)
class CaptureResult:
    image: bytes
    surface_id: str
    surface_kind: str
    width: int
    height: int
    captured_at: str
    sequence: int
    viewport_revision: str
    url: str | None = None
    title: str | None = None
    cursor: dict | None = None
    transform: dict | None = None
    action_id: str | None = None

    def metadata(self):
        return {key: value for key, value in asdict(self).items() if key != "image"}


class CaptureImage(bytes):
    """Bytes-compatible bridge for existing model SDK image blocks."""
    def __new__(cls, result: CaptureResult):
        value = super().__new__(cls, result.image)
        value.metadata = result.metadata()
        return value


class TerminationUnverified(SandboxError):
    """The caller must not admit another sandbox writer."""


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


@dataclass
class CommandResult:
    command_id: str
    exit_code: int | None
    stdout: str = ""
    stderr: str = ""
    stdout_truncated: bool = False
    stderr_truncated: bool = False
    timed_out: bool = False
    cancelled: bool = False
    started_at: str = field(default_factory=utc_now)
    ended_at: str = field(default_factory=utc_now)

    @property
    def ok(self) -> bool:
        return self.exit_code == 0 and not self.timed_out and not self.cancelled

    def text(self) -> str:
        output = "\n".join(part for part in (self.stdout, self.stderr) if part)
        if self.cancelled:
            output = "bash error: command cancelled.\n" + output
        elif self.timed_out:
            output = "bash error: command timed out.\n" + output
        elif self.exit_code != 0:
            output = (
                f"exit {self.exit_code if self.exit_code is not None else 'unknown'}\n"
                + output
            )
        if self.stdout_truncated or self.stderr_truncated:
            output += "\n...[truncated]"
        return output


@dataclass
class ActionResult:
    ok: bool
    text: str = ""
    command: CommandResult | None = None
    value: Any = None  # Adapter-private result (images, tool blocks); never serialized.
    cancelled: bool = False
    started_at: str = field(default_factory=utc_now)
    ended_at: str = field(default_factory=utc_now)

    def public(self) -> dict[str, Any]:
        result = dict(
            ok=self.ok,
            stdout=self.text,
            stderr="",
            exit_code=None,
            command_id=None,
            stdout_truncated=False,
            stderr_truncated=False,
            timed_out=False,
            cancelled=self.cancelled,
            started_at=self.started_at,
            ended_at=self.ended_at,
        )
        if self.command:
            result.update(asdict(self.command))
        if isinstance(self.value, dict) and "effect_observed" in self.value:
            result["effect_observed"] = self.value["effect_observed"] is True
        if isinstance(self.value, dict):
            if "outcome_unknown" in self.value:
                result["outcome_unknown"] = self.value["outcome_unknown"] is True
            if type(self.value.get("dispatched")) is bool:
                result["dispatched"] = self.value["dispatched"]
            if isinstance(self.value.get("code"), str) and self.value["code"] in {
                "stale_target", "permit_expired", "preflight_failed", "unsupported_text_control", "text_method_changed", "editor_not_focused"
            }:
                result["code"] = self.value["code"]
        return result


@dataclass
class DesktopResult:
    """Outcome of one computer-use member action."""

    ok: bool
    text: str = ""
    image: bytes | None = None
    error: str | None = None


class ISandboxClient(ABC):
    """Isolated OS execution environment, with no LLM concepts."""

    @abstractmethod
    async def run_bash(self, command: str) -> str:
        """Execute a command inside the secure environment and return its output."""

    async def run_command(self, command: str) -> CommandResult:
        """Compatibility for text-only third-party sandboxes: exit status is unknown."""
        started = utc_now()
        output = await self.run_bash(command)
        return CommandResult(uuid.uuid4().hex, None, stdout=output, started_at=started)

    @abstractmethod
    async def browser_click(self, selector: str) -> bytes:
        """Click a CSS selector in the persistent Playwright page and return a PNG."""

    @abstractmethod
    async def browser_open(self, url: str) -> bytes:
        """Open an http(s) URL in the persistent Playwright page and return a PNG."""

    @abstractmethod
    async def write_workspace_file(self, path: str, content: str) -> None:
        """Write a text file inside the virtual workspace."""

    @abstractmethod
    async def read_workspace_file(self, path: str) -> str:
        """Read a text file inside the virtual workspace."""

    @abstractmethod
    async def list_workspace(self, path: str) -> str:
        """List the names inside a workspace directory, one per line."""

    @abstractmethod
    async def workspace_kind(self, path: str) -> str:
        """Return ``file``, ``dir``, or ``missing`` for a workspace path."""

    @abstractmethod
    async def screenshot(self) -> bytes:
        """Capture the virtual desktop as PNG bytes."""

    @abstractmethod
    async def desktop_action(self, name: str, params: dict[str, Any]) -> DesktopResult:
        """Run one computer-use member tool against the virtual desktop."""

    @abstractmethod
    async def close(self) -> None:
        """Destroy the environment."""


@runtime_checkable
class SandboxFactory(Protocol):
    async def get_or_create(self, session_id: str) -> ISandboxClient: ...
    async def close(self, session_id: str) -> None: ...


@runtime_checkable
class SandboxManager(SandboxFactory, Protocol):
    """Session manager methods the control plane used to probe with hasattr."""

    def configure_scope(self, namespace: str, deployment: str) -> None: ...
    def bind(self, session_id: str, bot_id: str, generation: int) -> None: ...
    async def legacy_candidate(self, bot_id: str) -> Any: ...
    async def inspect(self, session_id: str) -> dict: ...
    async def existing(self, session_id: str) -> ISandboxClient: ...
    async def reconcile(self, session_id: str, uncertain: bool) -> str: ...
    async def hibernate(self, session_id: str) -> None: ...


@runtime_checkable
class CheckedSandbox(Protocol):
    async def run_command_checked(
        self, command: str, *, expected: str | None = None
    ) -> CommandResult: ...
    async def write_workspace_file_checked(
        self, path: str, content: str, *, expected: str
    ) -> None: ...
    async def browser_open_scoped(self, url: str, *, expected: str) -> bytes: ...


@runtime_checkable
class CancellableSandbox(Protocol):
    async def cancel_commands(self) -> None: ...


@runtime_checkable
class UncertainSandbox(Protocol):
    uncertain: bool
    uncertain_reason: str


@runtime_checkable
class ProtocolSandbox(Protocol):
    async def approval_protocol(self) -> int | None: ...


@runtime_checkable
class FileServiceSandbox(Protocol):
    async def files(self, operation: str, **arguments: Any) -> dict: ...


@runtime_checkable
class RevisionSandbox(Protocol):
    async def workspace_revision(self) -> str: ...
    async def file_revision(self, path: str) -> str: ...


class IAgentFrameworkAdapter(ABC):
    """Lifecycle every runtime framework must implement."""

    @abstractmethod
    async def initialize(
        self,
        sandbox: ISandboxClient,
        memory_context: list[dict[str, Any]],
        state_streamer: Any,
        instructions: str = "",
        model: ModelConfig | None = None,
    ) -> None:
        """Wire the sandbox, memory, event stream, and optional model credential into the engine."""

    @abstractmethod
    def execute_step(self, prompt: str) -> AsyncIterator[dict[str, Any]]:
        """Run one user turn and yield unified platform event frames."""
