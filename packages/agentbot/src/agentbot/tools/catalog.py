"""Specs plus the factories that implement extension tools."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from agentbot.tools.context import ToolAccess
from agentbot.tools.registry import ToolSpec


class ToolCatalog:
    """The tool set loaded for one control process."""

    def __init__(
        self,
        specs: Mapping[str, ToolSpec],
        factories: Mapping[str, Callable[..., Callable[..., Awaitable[str]]]] | None = None,
    ) -> None:
        self.specs = dict(specs)
        self.factories = dict(factories or {})
        known = {spec.tool_id for spec in self.specs.values()}
        missing = sorted(set(self.factories) - known)
        if missing:
            raise ValueError(f"Factory without a tool spec: {', '.join(missing)}")

    def get(self, key: str) -> ToolSpec | None:
        return self.specs.get(key)

    def access(
        self,
        bindings: list[dict[str, Any]],
        *,
        validate: Callable[[dict[str, Any]], None] | None = None,
    ) -> ToolAccess:
        return ToolAccess(
            bindings,
            validate=validate,
            registry=self.specs,
            factories=self.factories,
        )
