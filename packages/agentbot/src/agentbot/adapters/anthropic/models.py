from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from agentbot.interfaces import (
    CommandResult,
)


@dataclass
class ToolUse:
    id: str
    name: str
    toolset_name: str | None
    input: dict[str, Any]


@dataclass
class ModelTurn:
    stop_reason: str
    text: str
    tool_uses: list[ToolUse] = field(default_factory=list)
    raw_content: list[dict[str, Any]] = field(default_factory=list)


class CompletionClient(Protocol):
    async def complete(self, *, messages: list[dict[str, Any]], system: str) -> ModelTurn: ...


@dataclass
class ToolOutcome:
    ok: bool
    content: Any
    is_error: bool = False
    image: bytes | None = None
    artifact_path: str | None = None
    artifact_preview: str | None = None
    command: CommandResult | None = None
