from __future__ import annotations

from typing import Any

from agentbot.adapters.anthropic.constants import BASH_NAME, EDITOR_NAME, OBSERVATIONS
from agentbot.adapters.anthropic.models import ModelTurn, ToolOutcome, ToolUse
from agentbot.sandbox.desktop_plan import COMPUTER_ACTIONS


def _needs_approval(block: ToolUse) -> bool:
    if block.name in COMPUTER_ACTIONS and block.name in OBSERVATIONS:
        return False
    if block.name == EDITOR_NAME and block.input.get("command") == "view":
        return False
    return True


def _detail(block: ToolUse) -> str:
    if block.name == BASH_NAME:
        return str(block.input.get("command", ""))
    if block.name == EDITOR_NAME:
        return f"{block.input.get('command', '')} {block.input.get('path', '')}".strip()
    coordinate = block.input.get("coordinate")
    if coordinate:
        return f"{block.name} {coordinate}"
    return block.name


def _text_message(role: str, text: str) -> dict[str, Any]:
    return {"role": role, "content": [{"type": "text", "text": text}]}


def _raw_from_uses(turn: ModelTurn) -> list[dict[str, Any]]:
    content: list[dict[str, Any]] = []
    if turn.text:
        content.append({"type": "text", "text": turn.text})
    for block in turn.tool_uses:
        item: dict[str, Any] = {
            "type": "tool_use",
            "id": block.id,
            "name": block.name,
            "input": block.input,
        }
        if block.toolset_name:
            item["toolset_name"] = block.toolset_name
        content.append(item)
    return content


def _error_result(block: ToolUse, message: str) -> dict[str, Any]:
    result: dict[str, Any] = {
        "type": "tool_result",
        "tool_use_id": block.id,
        "is_error": True,
        "content": message,
    }
    if block.toolset_name:
        result["toolset_name"] = block.toolset_name
    return result


def _result_from_outcome(block: ToolUse, outcome: ToolOutcome) -> dict[str, Any]:
    if not outcome.ok:
        return _error_result(block, str(outcome.content))
    result: dict[str, Any] = {
        "type": "tool_result",
        "tool_use_id": block.id,
        "content": outcome.content,
    }
    if block.toolset_name:
        result["toolset_name"] = block.toolset_name
    return result
