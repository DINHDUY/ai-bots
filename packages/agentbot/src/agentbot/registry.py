"""Dependency-injection registry for framework adapters."""

from __future__ import annotations

import logging
from collections.abc import Callable

from agentbot.interfaces import IAgentFrameworkAdapter

logger = logging.getLogger("AgentBotKernel")


class FrameworkRegistry:
    """Resolves a framework name to a new adapter instance."""

    def __init__(self) -> None:
        self._registry: dict[str, Callable[[], IAgentFrameworkAdapter]] = {}

    def register_framework(self, name: str, adapter_cls: Callable[[], IAgentFrameworkAdapter]) -> None:
        self._registry[name.lower()] = adapter_cls
        logger.info("Registered framework into system metadata: '%s'", name)

    def known(self, name: str) -> bool:
        return name.lower() in self._registry

    def resolve(self, name: str) -> IAgentFrameworkAdapter:
        adapter_cls = self._registry.get(name.lower())
        if not adapter_cls:
            raise ValueError(f"Target framework engine '{name}' could not be resolved.")
        return adapter_cls()
