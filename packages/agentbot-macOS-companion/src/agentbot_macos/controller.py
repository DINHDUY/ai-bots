"""Thin runtime coordination. Planning and native input live behind the runtime API."""

import json
from collections.abc import Awaitable, Callable
from typing import Any, Protocol

from agentbot_macos.actions import MacAction


class RuntimeClient(Protocol):
    async def observe(self) -> dict: ...
    async def planner(self, operation: str, **arguments: Any) -> dict: ...


class NativeRuntimeClient(RuntimeClient, Protocol):
    async def execute_macos(self, action: dict) -> dict: ...


class OiController:
    def __init__(self, runtime: RuntimeClient, complete: Callable[[list], Awaitable[str]]):
        self.runtime, self.complete = runtime, complete

    async def start(self, goal: str, instructions: str = "", context: list | None = None):
        await self.runtime.planner(
            "start", request=goal, instructions=instructions, context=context or []
        )

    async def next(self) -> dict:
        observation = await self.runtime.observe()
        prepared = await self.runtime.planner("prompt", observation=observation)
        if prepared.get("role") != "OIPlanner":
            raise ValueError("Unsupported Open-Interface planning role")
        response = await self.complete(prepared["messages"])
        try:
            candidate = json.loads(response)
        except (ValueError, TypeError):
            candidate = None
        if isinstance(candidate, dict) and set(candidate) == {"peer_handled"}:
            return candidate
        result = await self.runtime.planner("response", response=response)
        if result.get("action"):
            result["action"] = MacAction.model_validate(result["action"]).model_dump()
        return result

    async def result(self, value: dict):
        await self.runtime.planner("result", result=value)
