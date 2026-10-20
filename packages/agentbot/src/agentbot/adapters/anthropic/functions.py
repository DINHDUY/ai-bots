"""Run selected factory tools without dropping approval frames."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from agentbot.adapters.anthropic.constants import ENGINE
from agentbot.interfaces import ActionResult
from agentbot.tools.context import ToolExecutionContext


@dataclass(frozen=True)
class FunctionResult:
    text: str


def bind_selected(adapter):
    async def action(operation, arguments, detail, execute):
        frames = adapter._function_frames
        if frames is None:
            raise RuntimeError("Tool action outside a model turn")
        result = None
        async for item in adapter.streamer.execute_action(
            ENGINE, operation, arguments, detail, execute
        ):
            if isinstance(item, ActionResult):
                result = item
            else:
                await frames.put(item)
        if result is None:
            raise RuntimeError("Missing action outcome")
        return result

    async def run_terminal_command(command: str) -> str:
        async def execute():
            command_result = await adapter.sandbox.run_command(command)
            return ActionResult(command_result.ok, command_result.text(), command=command_result)

        result = await action("bash", {"command": command}, command, execute)
        return result.text

    adapter._function_frames = None
    context = ToolExecutionContext(
        adapter.sandbox,
        action,
        run_terminal_command,
        getattr(adapter.streamer, "bot_id", None),
        getattr(adapter.streamer, "rid", None),
    )
    bound = adapter.tool_access.bind(context)
    return {name: adapter.tool_access.wrap(name, function) for name, function in bound.items()}


async def run_selected(adapter, name, arguments):
    queue: asyncio.Queue = asyncio.Queue()
    adapter._function_frames = queue

    async def run():
        try:
            text = await adapter._functions[name](**arguments)
        except TypeError as exc:
            await queue.put(FunctionResult(f"Invalid arguments: {exc}"))
            return
        except Exception as exc:
            await queue.put(exc)
            return
        await queue.put(FunctionResult(text if isinstance(text, str) else str(text)))

    task = asyncio.create_task(run())
    try:
        while True:
            item = await queue.get()
            if isinstance(item, Exception):
                raise item
            yield item
            if isinstance(item, FunctionResult):
                return
    finally:
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        adapter._function_frames = None
