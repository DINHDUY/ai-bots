from __future__ import annotations

import os
from typing import Any

from agentbot.adapters.anthropic.constants import BASH_NAME, EDITOR_NAME
from agentbot.adapters.anthropic.models import ModelTurn, ToolUse
from agentbot.tools import ToolAccess


class AnthropicMessagesClient:
    """Messages API client for the computer-use toolset."""

    def __init__(self, *, model: str | None = None, api_key: str | None = None) -> None:
        self.model = model or os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-5")
        self.api_key = api_key
        self.extra_tools = []
        self.tool_access = ToolAccess.legacy("anthropic")

    async def complete(self, *, messages: list[dict[str, Any]], system: str) -> ModelTurn:
        import anthropic

        client = (
            anthropic.AsyncAnthropic(api_key=self.api_key)
            if self.api_key
            else anthropic.AsyncAnthropic()
        )
        response = await client.messages.create(
            model=self.model,
            max_tokens=4096,
            system=system,
            tools=[
                *(
                    [{"type": "computer_toolset_20260801"}]
                    if self.tool_access.has("computer")
                    else []
                ),
                *(
                    [{"type": "text_editor_20250728", "name": EDITOR_NAME}]
                    if self.tool_access.has("text_editor")
                    else []
                ),
                *(
                    [{"type": "bash_20250124", "name": BASH_NAME}]
                    if self.tool_access.has("run_terminal_command")
                    else []
                ),
                *self.extra_tools,
            ],
            messages=messages,
        )
        return _parse_response(response)


def _parse_response(response: Any) -> ModelTurn:
    text_parts: list[str] = []
    uses: list[ToolUse] = []
    raw: list[dict[str, Any]] = []
    for block in response.content:
        dumped = (
            block.model_dump(exclude_none=True) if hasattr(block, "model_dump") else dict(block)
        )
        raw.append(dumped)
        block_type = dumped.get("type")
        if block_type == "text":
            text_parts.append(str(dumped.get("text", "")))
        elif block_type == "tool_use":
            uses.append(
                ToolUse(
                    id=str(dumped["id"]),
                    name=str(dumped["name"]),
                    toolset_name=dumped.get("toolset_name"),
                    input=dict(dumped.get("input") or {}),
                )
            )
    return ModelTurn(
        stop_reason=str(response.stop_reason),
        text="".join(text_parts),
        tool_uses=uses,
        raw_content=raw,
    )
