"""Microsoft Agent Framework adapter.

Tools are ordinary async functions so tests can run them without the SDK.
The default runner builds an Agent Framework agent when a step actually starts.
"""

from __future__ import annotations

import asyncio
import json
import os
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

from agentbot.adapters.conversation import bounded_history, conversational_intent
from agentbot.adapters.streaming import TextBatcher
from agentbot.adapters.telemetry import model_metrics_middleware
from agentbot.events import RealTimeEventStreamer
from agentbot.execution import RunYield as PeerWait
from agentbot.interfaces import (
    ActionResult,
    IAgentFrameworkAdapter,
    ISandboxClient,
    SandboxError,
)
from agentbot.models import ModelConfig
from agentbot.sandbox.paths import WorkspacePathError
from agentbot.tools import ToolAccess
from agentbot.tools.context import ToolExecutionContext

ENGINE = "MicrosoftAutoGenEngine"
BASE_INSTRUCTIONS = (
    "You are an assistant working in an isolated Linux sandbox. "
    "Follow this bot's configured instructions for its role and tasks. "
    "Answer the latest user message. History is background, not a queue of unfinished jobs. "
    "Greetings and status questions do not authorize resuming old work. For status, summarize "
    "what is known and distinguish earlier results from live state. Continue an earlier task "
    "only when the current request explicitly asks to continue or resume. Autopilot only "
    "approves actions for the requested task; it does not expand that task. "
    "Older history may be omitted. Ask for missing task details or credentials instead of guessing. "
    "Use only the tools available for this bot. "
    "Reuse successful observations within a task until their inputs change. Combine related "
    "read-only checks, prefer patch_file for small repairs, verify the result once, then finish. "
    "Re-observe after errors, operator changes, explicit resume, or a new computer generation."
)
ToolFn = Callable[..., Awaitable[str]]
TextCallback = Callable[[str], Awaitable[None]]
AgentRunner = Callable[
    [dict[str, ToolFn], str, list[dict[str, Any]], TextCallback], Awaitable[str]
]


def _with_extra_instructions(extra: str) -> str:
    extra = extra.strip()
    if not extra:
        return BASE_INSTRUCTIONS
    return f"{BASE_INSTRUCTIONS}\n\n{extra}"


class MicrosoftAgentAdapter(IAgentFrameworkAdapter):
    """Maps the sandbox onto Agent Framework function tools."""

    def __init__(
        self,
        *,
        runner: AgentRunner | None = None,
        model: str | None = None,
        max_tool_turns: int | None = None,
    ) -> None:
        self._runner = runner or _agent_framework_runner
        self._model = model or os.environ.get("OPENAI_MODEL", "gpt-4.1")
        self._max_tool_turns = max_tool_turns or int(
            os.environ.get("MAX_TOOL_TURNS", "20")
        )
        self.sandbox: ISandboxClient | None = None
        self.streamer: RealTimeEventStreamer | None = None
        self.context: list[dict[str, Any]] = []
        self._events: asyncio.Queue[dict[str, Any] | None] | None = None
        self._tools: dict[str, ToolFn] = {}
        self._turns = 0
        self._startup_frames: list[dict[str, Any]] = []
        self.instructions = ""
        self._model_config: ModelConfig | None = None
        self._text_batch: TextBatcher | None = None
        self.request_intent = "user"

    async def initialize(
        self,
        sandbox: ISandboxClient,
        memory_context: list[dict[str, Any]],
        state_streamer: RealTimeEventStreamer,
        instructions: str = "",
        model: ModelConfig | None = None,
    ) -> None:
        if model is not None and model.provider not in {"openai", "azure_foundry"}:
            raise RuntimeError(
                "MicrosoftAgentAdapter requires an openai or azure_foundry credential."
            )
        self._model_config = model
        self.sandbox = sandbox
        self.streamer = state_streamer
        self.instructions = instructions.strip()
        self.context = bounded_history(memory_context)
        self.request_intent = state_streamer.context.request_intent
        self.tool_access = state_streamer.context.tool_access or ToolAccess.legacy("microsoft")
        self._tools = {
            "run_terminal_command": self._run_terminal_command,
            "mutate_file": self._mutate_file,
            "patch_file": self._patch_file,
            "open_browser": self._open_browser,
            "browser_click": self._browser_click,
        }
        self._tools.update(self.tool_access.bind(ToolExecutionContext(
            sandbox, self._action, self._run_terminal_command,
            getattr(state_streamer, "bot_id", None), getattr(state_streamer, "rid", None),
        )))
        if self.streamer.context.connector_prepare is not None:
            self._tools["github_issues"] = self._github_issues
        if self.streamer.context.skill_execute is not None:
            self._tools["replay_skill"] = self._replay_skill
        self._tools = {
            name: self.tool_access.wrap(name, function)
            for name, function in self._tools.items() if self.tool_access.has(name)
        }
        self._tools.update(state_streamer.context.peer_tools)
        guidance = self.tool_access.guidance()
        if guidance:
            self.instructions += "\n\n" + guidance
        self._startup_frames = [
            self.streamer.emit_log(
                ENGINE,
                "SYSTEM",
                "Mapped sandbox capabilities to Agent Framework function tools.",
            )
        ]

    def execute_step(self, prompt: str) -> AsyncIterator[dict[str, Any]]:
        return self._execute(prompt)

    async def _execute(self, prompt: str) -> AsyncIterator[dict[str, Any]]:
        if self.sandbox is None or self.streamer is None:
            raise RuntimeError("MicrosoftAgentAdapter.initialize was not called.")
        self._turns = 0
        intent = conversational_intent(prompt)
        if intent == "greeting" and self.request_intent != "human_resume":
            yield self.streamer.emit_log(
                ENGINE, "RESULT", "Hello! What would you like me to work on?"
            )
            return
        queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()
        self._events = queue
        for frame in self._startup_frames:
            yield frame

        async def emit_text(text: str) -> None:
            assert self.streamer is not None
            await queue.put(self.streamer.emit_log(ENGINE, "THOUGHT", text))

        self._text_batch = TextBatcher(emit_text)
        on_text = self._text_batch.append
        tools = (
            {}
            if intent == "status" and self.request_intent != "human_resume"
            else self._tools
        )

        async def on_metrics(data):
            await self._emit({"event": "telemetry", "source": ENGINE, "data": data})

        async def run() -> None:
            assert self.streamer is not None
            try:
                if self._runner is _agent_framework_runner:
                    final = await _agent_framework_runner(
                        tools,
                        prompt,
                        self.context,
                        on_text,
                        instructions=self.instructions,
                        model=self._model_config,
                        fallback_model=self._model,
                        request_intent=self.request_intent,
                        on_metrics=on_metrics,
                        peer_roster=self.streamer.context.peer_roster,
                    )
                else:
                    final = await self._runner(tools, prompt, self.context, on_text)
                await self._text_batch.flush()
                await queue.put(self.streamer.emit_log(ENGINE, "RESULT", final or ""))
            except PeerWait:
                pass  # The backend committed a continuation; end this run segment.
            except Exception as exc:
                await self._text_batch.flush()
                await queue.put(self.streamer.emit_log(ENGINE, "ERROR", str(exc)))
            finally:
                await self._text_batch.flush()
                await queue.put(None)

        task = asyncio.create_task(run())
        try:
            while True:
                item = await queue.get()
                if item is None:
                    break
                yield item
        finally:
            if not task.done():
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    async def _action(self, operation, arguments, detail, execute) -> ActionResult:
        assert self.streamer is not None
        if self._text_batch:
            await self._text_batch.flush()
        self._turns += 1
        if self._turns > self._max_tool_turns:
            raise RuntimeError(f"Stopped after {self._max_tool_turns} tool calls.")
        result = None
        async for event in self.streamer.execute_action(
            ENGINE, operation, arguments, detail, execute
        ):
            if isinstance(event, ActionResult):
                result = event
            else:
                await self._emit(event)
        if result is not None:
            return result
        raise RuntimeError("Missing action outcome")

    async def _run_terminal_command(self, command: str) -> str:
        """Run a shell command inside the session sandbox."""
        assert self.sandbox is not None and self.streamer is not None

        async def execute():
            try:
                result = await self.sandbox.run_command(command)
                return ActionResult(result.ok, result.text(), command=result)
            except SandboxError as exc:
                return ActionResult(False, f"bash error: {exc}")

        result = await self._action("bash", {"command": command}, command, execute)
        await self._emit(
            self.streamer.emit_log(
                ENGINE, "TOOL_CALL", f"run_terminal_command: {command}\n{result.text}"
            )
        )
        return result.text

    async def _patch_file(self, path: str, old_text: str, new_text: str) -> str:
        """Replace exactly one literal match in a workspace text file; at most 8 KiB per side."""
        assert self.sandbox is not None and self.streamer is not None
        if not old_text or max(len(old_text.encode()), len(new_text.encode())) > 8192:
            return (
                "patch_file error: provide a nonempty match and at most 8 KiB per side."
            )

        async def execute():
            try:
                current = await self.sandbox.read_workspace_file(path)
                if len(current.encode()) > 65536 or current.count(old_text) != 1:
                    return ActionResult(
                        False,
                        "patch_file requires a file up to 64 KiB and exactly one match; include unique context.",
                    )
                updated = current.replace(old_text, new_text, 1)
                if len(updated.encode()) > 65536:
                    return ActionResult(False, "Patched file would exceed 64 KiB.")
                await self.sandbox.write_workspace_file(path, updated)
                return ActionResult(True, f"Patched {path}")
            except (SandboxError, WorkspacePathError, PermissionError) as exc:
                return ActionResult(False, f"patch_file error: {exc}")

        result = await self._action(
            "file_edit",
            {
                "command": "str_replace",
                "path": path,
                "old_str": old_text,
                "new_str": new_text,
            },
            path,
            execute,
        )
        if result.ok:
            await self._emit(self.streamer.emit_artifact(ENGINE, path, ""))
        return result.text

    async def _github_issues(
        self, connection_id: str, operation: str, title: str = "", text: str = ""
    ) -> str:
        """List or create repository issues using an installed backend GitHub connection."""
        prepare = self.streamer.context.connector_prepare
        execute_connector = self.streamer.context.connector_execute
        if prepare is None or execute_connector is None:
            raise RuntimeError("The selected connector is unavailable")
        arguments = prepare(
            connection_id, operation, title, text
        )
        result = await self._action(
            "connector.github",
            arguments,
            json.dumps(arguments),
            lambda: execute_connector(arguments),
        )
        return result.text

    async def _replay_skill(self, skill_id: str, parameters_json: str = "{}") -> str:
        """Replay one selected taught task with a JSON object of text parameters."""
        execute_skill = self.streamer.context.skill_execute
        if execute_skill is None:
            raise RuntimeError("The selected skill is unavailable")
        return await execute_skill(skill_id, parameters_json)

    async def _mutate_file(self, path: str, content: str) -> str:
        """Write a text file inside the workspace."""
        assert self.sandbox is not None and self.streamer is not None

        async def execute():
            try:
                await self.sandbox.write_workspace_file(path, content)
                return ActionResult(True, f"Wrote {len(content)} bytes to {path}")
            except (SandboxError, WorkspacePathError, PermissionError) as exc:
                return ActionResult(False, f"mutate_file error: {exc}")

        result = await self._action(
            "file_write", {"path": path, "content": content}, path, execute
        )
        if result.ok:
            await self._emit(self.streamer.emit_artifact(ENGINE, path, content[:200]))
            await self._emit(
                self.streamer.emit_log(ENGINE, "TOOL_CALL", f"mutate_file: {path}")
            )
        return result.text

    async def _open_browser(self, url: str) -> str:
        """Open an http or https URL in the sandbox browser."""
        return await self._browser_action("open_browser", "browser_open", "url", url)

    async def _browser_click(self, selector: str) -> str:
        """Click a CSS selector in the sandbox browser."""
        return await self._browser_action(
            "browser_click", "browser_click", "selector", selector
        )

    async def _browser_action(self, operation, method, argument, value) -> str:
        assert self.sandbox is not None and self.streamer is not None

        async def execute():
            try:
                image = await getattr(self.sandbox, method)(value)
                return ActionResult(
                    True,
                    f"{'Opened' if operation == 'open_browser' else 'Clicked'} {value}",
                    value=image,
                )
            except (SandboxError, PermissionError) as exc:
                return ActionResult(False, f"{operation} error: {exc}")

        result = await self._action(operation, {argument: value}, value, execute)
        if result.ok:
            await self._emit(
                self.streamer.emit_log(ENGINE, "TOOL_CALL", f"{operation}: {value}")
            )
            await self._emit(self.streamer.emit_screenshot(ENGINE, result.value))
        return result.text

    async def _emit(self, frame: dict[str, Any]) -> None:
        if self._events is None:
            return
        if self._text_batch:
            await self._text_batch.flush()
        await self._events.put(frame)


async def _agent_framework_runner(
    tools: dict[str, ToolFn],
    prompt: str,
    context: list[dict[str, Any]],
    on_text: TextCallback,
    instructions: str = "",
    model: ModelConfig | None = None,
    fallback_model: str | None = None,
    request_intent: str = "user",
    on_metrics=None,
    peer_roster=None,
) -> str:
    try:
        from agent_framework import Agent, Message, tool
        from agent_framework.openai import OpenAIChatClient
    except ImportError as exc:
        raise RuntimeError(
            "Microsoft Agent Framework is not installed. Install agent-framework and agent-framework-openai."
        ) from exc

    wrapped = [
        tool(name=name, approval_mode="never_require")(fn) for name, fn in tools.items()
    ]
    kwargs = chat_client_kwargs(model, fallback_model=fallback_model)
    middleware = [model_metrics_middleware(on_metrics)] if on_metrics is not None else []
    if peer_roster:
        from agentbot.adapters.context import roster_middleware
        middleware.append(roster_middleware(peer_roster))
    if middleware:
        kwargs["middleware"] = middleware
    agent = Agent(
        client=OpenAIChatClient(**kwargs),
        name=ENGINE,
        instructions=_with_extra_instructions(instructions),
        tools=wrapped,
    )
    messages = [
        Message(item["role"], [item["content"]]) for item in bounded_history(context)
    ]
    if request_intent == "human_resume":
        messages.append(
            Message(
                "system",
                [
                    "The operator explicitly selected Resume. Continue the previous task after re-observing files and the screen for operator changes. If the needed task details are absent, ask for them rather than guessing."
                ],
            )
        )
    messages.append(Message("user", [prompt]))
    pieces: list[str] = []
    async for update in agent.run(messages, stream=True):
        text = getattr(update, "text", None)
        if text:
            pieces.append(text)
            await on_text(text)
    return "".join(pieces)


def chat_client_kwargs(
    config: ModelConfig | None, *, fallback_model: str | None = None
) -> dict[str, str]:
    """Arguments for OpenAIChatClient. A missing config keeps the process env key."""

    if config is None:
        return {"model": fallback_model or os.environ.get("OPENAI_MODEL", "gpt-4.1")}
    if config.provider == "openai":
        return {"model": config.model, "api_key": config.api_key}
    if config.provider == "azure_foundry":
        return {
            "model": config.model,
            "api_key": config.api_key,
            "base_url": config.endpoint,
        }
    raise RuntimeError(
        "MicrosoftAgentAdapter requires an openai or azure_foundry credential."
    )
