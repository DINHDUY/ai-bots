"""Pinned tool access; a server-owned context follows composite child actions."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Generator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from functools import wraps
from typing import Any, ParamSpec, Protocol, TypeVar

from agentbot.interfaces import ActionResult, ISandboxClient
from agentbot.tools.registry import REGISTRY, ToolSpec, legacy_selection

current_tool: ContextVar[dict[str, Any] | None] = ContextVar("agentbot_current_tool", default=None)
P = ParamSpec("P")
T = TypeVar("T")


class ToolUnavailable(RuntimeError):
    pass


class ActionExecutor(Protocol):
    async def __call__(
        self,
        operation: str,
        arguments: dict[str, Any],
        detail: str,
        execute: Callable[[], Awaitable[ActionResult]],
        /,
    ) -> ActionResult: ...


@dataclass
class ToolExecutionContext:
    sandbox: ISandboxClient
    action: ActionExecutor
    run_terminal_command: Callable[[str], Awaitable[str]]
    bot_id: str | None = None
    run_id: str | None = None


class ToolAccess:
    def __init__(
        self,
        bindings: list[dict[str, Any]],
        *,
        validate: Callable[[dict[str, Any]], None] | None = None,
        registry: Mapping[str, ToolSpec] | None = None,
        factories: Mapping[str, Callable[[ToolExecutionContext], Callable[..., Awaitable[str]]]]
        | None = None,
    ) -> None:
        self.registry = REGISTRY if registry is None else registry
        self.factories = factories or {}
        self.bindings = bindings
        self.validate = validate

    def bind(self, context: ToolExecutionContext) -> dict[str, Callable[..., Awaitable[str]]]:
        """Bind only selected maintained extensions, retaining normal scope checks."""
        return {
            name: factory(context) for name, factory in self.factories.items() if self.has(name)
        }

    @classmethod
    def legacy(cls, framework: str) -> ToolAccess:
        return cls(legacy_selection(framework))

    def candidates(self, name: str) -> list[dict[str, Any]]:
        return [b for b in self.bindings if b["tool_id"] == name and b.get("ready", True)]

    def has(self, name: str) -> bool:
        return bool(self.candidates(name))

    def require(self, name: str, arguments: Mapping[str, Any] | None = None) -> dict[str, Any]:
        args = arguments or {}
        for binding in self.candidates(name):
            spec = self.registry[f"{binding['library_id']}/{name}"]
            resource_id = binding.get("configuration", {}).get("resource_id")
            if spec.resource and (
                not resource_id
                or resource_id
                != args.get("connection_id" if spec.resource == "connector" else "skill_id")
            ):
                continue
            if self.validate:
                self.validate(binding)
            return binding
        raise ToolUnavailable(
            f"Tool unavailable or removed: {name}. Configure tools in Bot settings and start a new task."
        )

    @contextmanager
    def scope(
        self, name: str, arguments: Mapping[str, Any] | None = None
    ) -> Generator[dict[str, Any], None, None]:
        binding = self.require(name, arguments)
        token = current_tool.set(binding)
        try:
            yield binding
        finally:
            current_tool.reset(token)

    def wrap(self, name: str, function: Callable[P, Awaitable[T]]) -> Callable[P, Awaitable[T]]:
        import inspect

        signature = inspect.signature(function)

        @wraps(function)
        async def invoke(*args: P.args, **kwargs: P.kwargs) -> T:
            arguments = signature.bind(*args, **kwargs).arguments
            with self.scope(name, arguments):
                return await function(*args, **kwargs)

        return invoke

    def operation(self, operation: str, arguments: Mapping[str, Any]) -> dict[str, Any]:
        binding = current_tool.get()
        if binding is None:
            name = {
                "bash": "run_terminal_command",
                "file_write": "mutate_file",
                "file_edit": "text_editor" if self.has("text_editor") else "patch_file",
                "connector.github": "github_issues",
            }.get(
                operation,
                operation,
            )
            bundles = {
                spec.tool_id
                for spec in self.registry.values()
                if any(
                    pattern.endswith(".*") and operation.startswith(pattern[:-1])
                    for pattern in spec.operations
                )
            }
            if len(bundles) == 1:
                name = next(iter(bundles))
            if name not in {b["tool_id"] for b in self.bindings}:
                # Anthropic's native computer members are exposed as one bundle.
                from agentbot.sandbox.desktop_plan import COMPUTER_ACTIONS

                if operation in COMPUTER_ACTIONS:
                    name = "computer"
            binding = self.require(name, arguments)
        elif self.validate:
            self.validate(binding)
        spec = self.registry[f"{binding['library_id']}/{binding['tool_id']}"]
        if spec.resource == "connector" and arguments.get("connection_id") != binding[
            "configuration"
        ].get("resource_id"):
            raise ToolUnavailable("The action does not use this tool's selected connection.")
        allowed = operation in spec.operations or (
            any(
                pattern.endswith(".*") and operation.startswith(pattern[:-1])
                for pattern in spec.operations
            )
        )
        if "computer.*" in spec.operations:
            from agentbot.sandbox.desktop_plan import COMPUTER_ACTIONS

            allowed = operation in COMPUTER_ACTIONS
        if not allowed:
            raise ToolUnavailable("This tool does not declare the requested action.")
        return binding

    def guidance(self) -> str:
        return "\n".join(
            dict.fromkeys(
                self.registry[f"{b['library_id']}/{b['tool_id']}"].guidance
                for b in self.bindings
                if b.get("ready", True)
            )
        ).strip()
