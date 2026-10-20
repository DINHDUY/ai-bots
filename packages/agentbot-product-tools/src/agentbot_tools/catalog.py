"""Compose maintained tools, CLI manifests, and allowlisted packages."""

from __future__ import annotations

from agentbot.tools.catalog import ToolCatalog
from agentbot.tools.registry import make_registry

from agentbot_tools.registry import REGISTRY


def maintained_catalog() -> ToolCatalog:
    return ToolCatalog(REGISTRY)


def load_catalog(*, manifests: str = "", allowlist: str = "") -> ToolCatalog:
    specs = list(REGISTRY.values())
    factories: dict = {}
    if manifests:
        from agentbot_tools.cli import load_manifests

        cli_specs, cli_factories = load_manifests(manifests)
        specs.extend(cli_specs)
        factories.update(cli_factories)
    if allowlist:
        from agentbot_tools.plugins import load_plugins

        plugin_specs, plugin_factories = load_plugins(allowlist)
        overlap = set(factories) & set(plugin_factories)
        if overlap:
            raise RuntimeError(f"CLI tool and plugin use the same id: {', '.join(sorted(overlap))}")
        specs.extend(plugin_specs)
        factories.update(plugin_factories)
    try:
        registry = make_registry(specs)
    except ValueError as exc:
        raise RuntimeError(f"Tool catalog rejected a plugin or CLI manifest: {exc}") from exc
    return ToolCatalog(registry, factories)
