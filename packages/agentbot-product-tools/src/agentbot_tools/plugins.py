"""Load allowlisted agentbot.tools entry points at process startup."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from agentbot.tools.registry import ToolSpec

from agentbot_tools.reserved import reserved_tool_ids

DIST = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
SHA = re.compile(r"^[0-9a-f]{64}$")


def load_plugins(path: str):
    allowlist = _allowlist(Path(path))
    if not allowlist:
        return [], {}
    from importlib.metadata import entry_points

    grouped: dict[str, list] = {}
    for entry in entry_points(group="agentbot.tools"):
        dist = entry.dist
        if dist is None:
            continue
        grouped.setdefault(_norm(dist.metadata["Name"]), []).append(entry)
    specs, factories = [], {}
    reserved = reserved_tool_ids()
    for item in allowlist:
        name = item["distribution"]
        found = grouped.get(_norm(name), [])
        if len(found) != 1:
            raise RuntimeError(
                f"Allowlisted plugin {name} needs exactly one agentbot.tools entry point; found {len(found)}."
            )
        entry = found[0]
        dist = entry.dist
        if dist is None:
            raise RuntimeError(f"Allowlisted plugin {name} has no installed distribution.")
        if dist.version != item["version"]:
            raise RuntimeError(
                f"Plugin {name} version is {dist.version}, not allowlisted {item['version']}."
            )
        record = dist.read_text("RECORD")
        if not record or hashlib.sha256(record.encode()).hexdigest() != item["record_sha256"]:
            raise RuntimeError(f"Plugin {name} RECORD hash does not match the allowlist.")
        loaded = entry.load()
        value = loaded() if callable(loaded) else loaded
        plugin_specs, plugin_factories = _plugin(value, dist.metadata["Name"], dist.version, entry)
        for spec in plugin_specs:
            if spec.tool_id in reserved or spec.tool_id in factories:
                raise RuntimeError(f"Plugin tool id is reserved or duplicated: {spec.tool_id}")
            if any(other.tool_id == spec.tool_id for other in specs):
                raise RuntimeError(f"Plugin tool id is reserved or duplicated: {spec.tool_id}")
        specs.extend(plugin_specs)
        factories.update(plugin_factories)
    return specs, factories


def _allowlist(path: Path):
    if not path.is_file():
        raise RuntimeError(f"Tool plugin allowlist was not found: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Tool plugin allowlist is not valid JSON: {path}") from exc
    plugins = data.get("plugins") if isinstance(data, dict) else None
    if not isinstance(plugins, list) or set(data) != {"plugins"}:
        raise RuntimeError("Tool plugin allowlist must be an object with a plugins list.")
    parsed = []
    seen = set()
    for item in plugins:
        if not isinstance(item, dict) or set(item) != {"distribution", "version", "record_sha256"}:
            raise RuntimeError(
                "Each allowlist plugin needs distribution, version, and record_sha256."
            )
        name, version, digest = item["distribution"], item["version"], item["record_sha256"]
        if (
            not isinstance(name, str)
            or not DIST.fullmatch(name)
            or not isinstance(version, str)
            or not version
            or len(version) > 64
            or not isinstance(digest, str)
            or not SHA.fullmatch(digest)
        ):
            raise RuntimeError(f"Invalid allowlist entry for {name!r}.")
        if _norm(name) in seen or _prefix(name) == "plugin.cli.":
            raise RuntimeError(f"Duplicate or reserved plugin distribution: {name}")
        seen.add(_norm(name))
        parsed.append(item)
    return parsed


def _plugin(value, name, version, entry):
    if not isinstance(value, dict) or set(value) != {"specs", "factories"}:
        raise RuntimeError(f"Plugin {name} must return specs and factories.")
    specs = tuple(value["specs"])
    factories = dict(value["factories"])
    if not specs or any(not isinstance(spec, ToolSpec) for spec in specs):
        raise RuntimeError(f"Plugin {name} must return ToolSpec values.")
    module = entry.value.split(":", 1)[0]
    prefix = _prefix(name)
    pinned = []
    for spec in specs:
        if not spec.library_id.startswith(prefix):
            raise RuntimeError(f"Plugin {name} library id must start with {prefix}")
        if set(spec.frameworks) - {"microsoft", "anthropic"} or not spec.frameworks:
            raise RuntimeError(f"Plugin {spec.key} can target microsoft and anthropic only.")
        if not spec.operations:
            raise RuntimeError(f"Plugin {spec.key} must declare at least one action.")
        pinned.append(
            spec
            if spec.distribution == name
            and spec.implementation_modules
            and spec.provenance == f"Installed plugin {name}=={version}"
            else _pin(spec, name, version, module)
        )
    if set(factories) != {spec.tool_id for spec in pinned} or any(
        not callable(item) for item in factories.values()
    ):
        raise RuntimeError(f"Plugin {name} factories must match its tool ids.")
    return pinned, factories


def _pin(spec, name, version, module):
    from dataclasses import replace

    return replace(
        spec,
        distribution=name,
        implementation_modules=spec.implementation_modules or (module,),
        provenance=f"Installed plugin {name}=={version}",
    )


def _norm(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.casefold()).strip("-")


def _prefix(name: str) -> str:
    return "plugin." + re.sub(r"[^a-z0-9]+", "_", name.casefold()).strip("_") + "."
