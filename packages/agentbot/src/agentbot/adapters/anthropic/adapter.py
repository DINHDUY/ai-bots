from __future__ import annotations

import base64
import json
import os
from collections.abc import AsyncIterator
from typing import Any

from agentbot.adapters.anthropic.client import AnthropicMessagesClient
from agentbot.adapters.anthropic.constants import (
    BASH_NAME,
    EDITOR_NAME,
    ENGINE,
    HALT_TEXT,
    SYSTEM_PROMPT,
)
from agentbot.adapters.anthropic.models import CompletionClient, ToolOutcome, ToolUse
from agentbot.adapters.anthropic.results import (
    _detail,
    _error_result,
    _needs_approval,
    _raw_from_uses,
    _result_from_outcome,
    _text_message,
)
from agentbot.events import RealTimeEventStreamer
from agentbot.execution import RunYield as PeerWait
from agentbot.interfaces import (
    ActionResult,
    IAgentFrameworkAdapter,
    ISandboxClient,
    SandboxError,
)
from agentbot.models import ModelConfig
from agentbot.sandbox.desktop_plan import COMPUTER_ACTIONS
from agentbot.sandbox.paths import WorkspacePathError
from agentbot.tools import ToolAccess


class ClaudeAgentAdapter(IAgentFrameworkAdapter):
    """Drives the computer-use, bash, and text-editor tools against the sandbox."""

    def __init__(
        self, *, client: CompletionClient | None = None, max_steps: int | None = None
    ) -> None:
        self._client = client or AnthropicMessagesClient()
        self._max_steps = max_steps or int(os.environ.get("MAX_AGENT_STEPS", "25"))
        self.sandbox: ISandboxClient | None = None
        self.streamer: RealTimeEventStreamer | None = None
        self.context: list[dict[str, Any]] = []
        self.instructions = ""

    async def initialize(
        self,
        sandbox: ISandboxClient,
        memory_context: list[dict[str, Any]],
        state_streamer: RealTimeEventStreamer,
        instructions: str = "",
        model: ModelConfig | None = None,
    ) -> None:
        if model is not None:
            if model.provider != "anthropic":
                raise RuntimeError("ClaudeAgentAdapter requires an anthropic credential.")
            if isinstance(self._client, AnthropicMessagesClient):
                self._client = AnthropicMessagesClient(model=model.model, api_key=model.api_key)
        self.sandbox = sandbox
        self.streamer = state_streamer
        self.tool_access = state_streamer.context.tool_access or ToolAccess.legacy("anthropic")
        if isinstance(self._client, AnthropicMessagesClient):
            self._client.tool_access = self.tool_access
            self._client.extra_tools = [
                t for t in state_streamer.context.connector_tools if self.tool_access.has(t["name"])
            ]
            self._client.extra_tools += state_streamer.context.peer_schemas
        self.instructions = (instructions.strip() + "\n" + self.tool_access.guidance()).strip()
        self.context = [
            _text_message(item["role"], str(item.get("content", ""))) for item in memory_context
        ]
        yield_frame = self.streamer.emit_log(
            ENGINE,
            "SYSTEM",
            "Bound sandbox drivers to Anthropic computer_toolset_20260801 schema blocks.",
        )
        self._startup_frame = yield_frame

    def _system_prompt(self) -> str:
        if not self.instructions:
            return SYSTEM_PROMPT
        return f"{SYSTEM_PROMPT}\n\n{self.instructions}"

    def execute_step(self, prompt: str) -> AsyncIterator[dict[str, Any]]:
        return self._execute(prompt)

    async def _execute(self, prompt: str) -> AsyncIterator[dict[str, Any]]:
        if self.sandbox is None or self.streamer is None:
            raise RuntimeError("ClaudeAgentAdapter.initialize was not called.")
        startup = getattr(self, "_startup_frame", None)
        if startup is not None:
            yield startup
        messages = list(self.context)
        messages.append(_text_message("user", prompt))
        for _step in range(self._max_steps):
            roster = self.streamer.context.peer_roster
            turn = await self._client.complete(
                messages=messages,
                system=self._system_prompt() + ("\n" + roster() if roster else ""),
            )
            if turn.text:
                yield self.streamer.emit_log(ENGINE, "THOUGHT", turn.text)
            if turn.stop_reason != "tool_use" or not turn.tool_uses:
                yield self.streamer.emit_log(ENGINE, "RESULT", turn.text)
                return
            results: list[dict[str, Any]] = []
            failed = False
            for block in turn.tool_uses:
                if failed:
                    results.append(_error_result(block, HALT_TEXT))
                    continue
                if block.name in self.streamer.context.peer_tools:
                    try:
                        text = await self.streamer.context.peer_tools[block.name](**block.input)
                    except PeerWait:
                        return
                    results.append(_result_from_outcome(block, ToolOutcome(ok=True, content=text)))
                    continue
                self._require_tool(block)
                if block.name == "replay_skill":
                    with self.tool_access.scope("replay_skill", block.input):
                        execute_skill = self.streamer.context.skill_execute
                        if execute_skill is None:
                            raise RuntimeError("The selected skill is unavailable")
                        text = await execute_skill(**block.input)
                    results.append(_result_from_outcome(block, ToolOutcome(ok=True, content=text)))
                    continue
                if (
                    block.name == "github_issues"
                    and self.streamer.context.connector_prepare is not None
                ):
                    block.input = self.streamer.context.connector_prepare(**block.input)

                async def dispatch() -> ActionResult:
                    tool_result = await self._dispatch(block)
                    return ActionResult(
                        tool_result.ok,
                        tool_result.content if isinstance(tool_result.content, str) else "",
                        command=tool_result.command,
                        value=tool_result,
                    )

                operation = "file_edit" if block.name == EDITOR_NAME else block.name
                if block.name == "github_issues":
                    operation = "connector.github"
                action_result = None
                async for event in self.streamer.execute_action(
                    ENGINE,
                    operation,
                    block.input,
                    json.dumps(block.input) if block.name == "github_issues" else _detail(block),
                    dispatch,
                    requires_approval=_needs_approval(block),
                ):
                    if isinstance(event, ActionResult):
                        action_result = event
                    else:
                        yield event
                assert action_result is not None
                if action_result.value is None:
                    results.append(_error_result(block, action_result.text))
                    failed = True
                    continue
                outcome = action_result.value
                message = f"{block.name}: {_detail(block)}"
                if block.name == BASH_NAME and isinstance(outcome.content, str) and outcome.content:
                    message = f"{message}\n{outcome.content}"
                yield self.streamer.emit_log(ENGINE, "TOOL_CALL", message)
                if outcome.image:
                    yield self.streamer.emit_screenshot(ENGINE, outcome.image)
                if outcome.artifact_path is not None:
                    yield self.streamer.emit_artifact(
                        ENGINE, outcome.artifact_path, outcome.artifact_preview or ""
                    )
                results.append(_result_from_outcome(block, outcome))
                if not outcome.ok:
                    failed = True
            messages.append(
                {
                    "role": "assistant",
                    "content": turn.raw_content or _raw_from_uses(turn),
                }
            )
            messages.append({"role": "user", "content": results})
        yield self.streamer.emit_log(ENGINE, "ERROR", f"Stopped after {self._max_steps} steps.")
        yield self.streamer.emit_log(ENGINE, "RESULT", "")

    def _require_tool(self, block):
        name = {BASH_NAME: "run_terminal_command", EDITOR_NAME: "text_editor"}.get(
            block.name, block.name
        )
        if block.name in COMPUTER_ACTIONS:
            name = "computer"
        self.tool_access.require(name, block.input)

    async def _dispatch(self, block: ToolUse) -> ToolOutcome:
        self._require_tool(block)
        assert self.sandbox is not None
        try:
            if (
                block.name == "github_issues"
                and self.streamer.context.connector_execute is not None
            ):
                result = await self.streamer.context.connector_execute(block.input)
                return ToolOutcome(ok=result.ok, is_error=not result.ok, content=result.text)
            if block.toolset_name == "computer" or (
                block.toolset_name in (None, "") and block.name in COMPUTER_ACTIONS
            ):
                return await self._computer(block)
            if block.name == BASH_NAME:
                return await self._bash(block.input)
            if block.name == EDITOR_NAME:
                return await self._editor(block.input)
            return ToolOutcome(ok=False, is_error=True, content=f"Unknown tool {block.name}.")
        except (SandboxError, WorkspacePathError, PermissionError, ValueError) as exc:
            return ToolOutcome(ok=False, is_error=True, content=str(exc))

    async def _computer(self, block: ToolUse) -> ToolOutcome:
        assert self.sandbox is not None
        result = await self.sandbox.desktop_action(block.name, block.input)
        if not result.ok:
            return ToolOutcome(
                ok=False,
                is_error=True,
                content=result.error or "computer action failed",
            )
        if result.image is not None:
            encoded = base64.b64encode(result.image).decode("ascii")
            return ToolOutcome(
                ok=True,
                image=result.image,
                content=[
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/png",
                            "data": encoded,
                        },
                    }
                ],
            )
        return ToolOutcome(ok=True, content=[{"type": "text", "text": result.text or "OK"}])

    async def _bash(self, payload: dict[str, Any]) -> ToolOutcome:
        assert self.sandbox is not None
        if payload.get("restart"):
            return ToolOutcome(ok=True, content="Bash session restarted")
        command = payload.get("command")
        if not isinstance(command, str) or not command:
            raise ValueError("bash requires a command.")
        result = await self.sandbox.run_command(command)
        return ToolOutcome(
            ok=result.ok,
            is_error=not result.ok,
            content=result.text() or "(no output)",
            command=result,
        )

    async def _editor(self, payload: dict[str, Any]) -> ToolOutcome:
        assert self.sandbox is not None
        command = str(payload.get("command", ""))
        path = str(payload.get("path", ""))
        if command == "view":
            return ToolOutcome(ok=True, content=await self._view(path, payload.get("view_range")))
        if command == "create":
            file_text = payload.get("file_text")
            if not isinstance(file_text, str):
                raise ValueError("create requires file_text.")
            if await self.sandbox.workspace_kind(path) != "missing":
                raise ValueError(f"File already exists: {path}")
            await self.sandbox.write_workspace_file(path, file_text)
            return ToolOutcome(
                ok=True,
                content=f"File created successfully at: {path}",
                artifact_path=path,
                artifact_preview=file_text[:200],
            )
        if command == "str_replace":
            old = payload.get("old_str")
            new = payload.get("new_str", "")
            if not isinstance(old, str) or old == "":
                raise ValueError("str_replace requires old_str.")
            if not isinstance(new, str):
                raise ValueError("str_replace requires new_str.")
            current = await self.sandbox.read_workspace_file(path)
            count = current.count(old)
            if count == 0:
                raise ValueError("old_str was not found in the file.")
            if count > 1:
                raise ValueError("old_str matched more than once; include more context.")
            updated = current.replace(old, new, 1)
            await self.sandbox.write_workspace_file(path, updated)
            return ToolOutcome(
                ok=True,
                content=f"Updated {path}",
                artifact_path=path,
                artifact_preview=updated[:200],
            )
        if command == "insert":
            insert_line = payload.get("insert_line")
            insert_text = payload.get("insert_text")
            if not isinstance(insert_line, int):
                raise ValueError("insert requires insert_line.")
            if not isinstance(insert_text, str):
                raise ValueError("insert requires insert_text.")
            current = await self.sandbox.read_workspace_file(path)
            lines = current.splitlines(keepends=True)
            if insert_line < 0 or insert_line > len(lines):
                raise ValueError("insert_line is out of range.")
            text = (
                insert_text
                if insert_text.endswith("\n") or insert_text == ""
                else insert_text + "\n"
            )
            lines.insert(insert_line, text)
            updated = "".join(lines)
            await self.sandbox.write_workspace_file(path, updated)
            return ToolOutcome(
                ok=True,
                content=f"Inserted text in {path}",
                artifact_path=path,
                artifact_preview=updated[:200],
            )
        raise ValueError(f"Unrecognized editor command {command}.")

    async def _view(self, path: str, view_range: Any) -> str:
        assert self.sandbox is not None
        kind = await self.sandbox.workspace_kind(path)
        if kind == "missing":
            raise SandboxError(f"No such path: {path}")
        if kind == "dir":
            listing = await self.sandbox.list_workspace(path)
            return f"Directory: {path}\n{listing}"
        content = await self.sandbox.read_workspace_file(path)
        lines = content.splitlines()
        if not lines and view_range is None:
            return ""
        start, end = 1, len(lines)
        if view_range is not None:
            if not isinstance(view_range, (list, tuple)) or len(view_range) != 2:
                raise ValueError("view_range must be [start, end].")
            start = int(view_range[0])
            end = len(lines) if int(view_range[1]) == -1 else int(view_range[1])
            if start < 1 or end < start or end > len(lines):
                raise ValueError("view_range is out of range.")
        selected = lines[start - 1 : end]
        numbered = "\n".join(f"{index + start:6}\t{line}" for index, line in enumerate(selected))
        if len(numbered) > 16_000:
            numbered = numbered[:16_000] + "\n...[truncated]"
        return numbered
