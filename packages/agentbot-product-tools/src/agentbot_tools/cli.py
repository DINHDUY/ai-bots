"""CLI manifests: a fixed argument list, quoted values, one sandbox command."""

from __future__ import annotations

import hashlib
import json
import re
import shlex
import tomllib
from pathlib import Path

from agentbot.interfaces import ActionResult
from agentbot.tools.registry import ToolSpec

from agentbot_tools.reserved import reserved_tool_ids
from agentbot_tools.signature import IDENT, bind_parameters

STATIC = re.compile(r"^[A-Za-z0-9_./:=@+\-,]+$")
PLACEHOLDER = re.compile(r"^\{([a-z][a-z0-9_]{0,63})\}$")
VERSION = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")
LIBRARY = "plugin.cli"


def load_manifests(directory: str):
    root = Path(directory)
    if not root.is_dir():
        raise RuntimeError(f"CLI tool manifest directory was not found: {root}")
    specs, factories = [], {}
    for path in sorted(root.glob("*.toml")):
        if path.stat().st_size > 16384:
            raise RuntimeError(f"CLI manifest exceeds 16 KiB: {path.name}")
        spec, factory = parse_manifest(path)
        if spec.tool_id in factories:
            raise RuntimeError(f"Duplicate CLI tool id: {spec.tool_id}")
        specs.append(spec)
        factories[spec.tool_id] = factory
    return specs, factories


def parse_manifest(path: Path):
    raw = path.read_bytes()
    try:
        data = tomllib.loads(raw.decode("utf-8"))
    except (UnicodeError, tomllib.TOMLDecodeError) as exc:
        raise RuntimeError(f"Invalid CLI manifest {path.name}: {exc}") from exc
    tool_id = _text(data, "tool_id", path)
    if not IDENT.fullmatch(tool_id) or tool_id in reserved_tool_ids():
        raise RuntimeError(f"CLI tool id is reserved or invalid: {tool_id}")
    name = _text(data, "name", path)
    description = _text(data, "description", path)
    binary = _text(data, "binary", path)
    version = data.get("version", "1.0.0")
    if not isinstance(version, str) or not VERSION.fullmatch(version):
        raise RuntimeError(f"{path.name}: version must be major.minor.patch")
    frameworks = data.get("frameworks", ["microsoft", "anthropic"])
    if (
        not isinstance(frameworks, list)
        or not frameworks
        or any(item not in {"microsoft", "anthropic"} for item in frameworks)
    ):
        raise RuntimeError(f"{path.name}: frameworks must be microsoft and/or anthropic")
    argv = data.get("argv")
    if (
        not isinstance(argv, list)
        or not 1 <= len(argv) <= 32
        or any(not isinstance(part, str) for part in argv)
        or argv[0] != binary
    ):
        raise RuntimeError(f"{path.name}: argv must be 1-32 strings starting with binary")
    parameters, optional, limits = _parameters(data.get("parameters", {}), path)
    _check_placeholders(argv, parameters, path)
    timeout = data.get("timeout_seconds", 30)
    output_limit = data.get("output_limit", 8000)
    if type(timeout) is not int or not 1 <= timeout <= 120:
        raise RuntimeError(f"{path.name}: timeout_seconds must be an integer from 1 to 120")
    if type(output_limit) is not int or not 1 <= output_limit <= 64000:
        raise RuntimeError(f"{path.name}: output_limit must be an integer from 1 to 64000")
    schema = {
        "type": "object",
        "properties": {
            key: {"type": "string", "maxLength": limits[key], "description": parameters[key]}
            for key in parameters
        },
        "required": [key for key in parameters if key not in optional],
        "additionalProperties": False,
    }
    guidance = (
        f"Run {binary} through the approved CLI wrapper. Arguments fill a fixed argument list. "
        f"The computer's command timeout applies (manifest guidance: {timeout} seconds)."
    )
    spec = ToolSpec(
        LIBRARY,
        "CLI tools",
        tool_id,
        name,
        description,
        tuple(frameworks),
        (f"cli.{tool_id}",),
        ("run_command",),
        version=version,
        guidance=guidance,
        adapter_modules=("agentbot_tools.cli",),
        parameters=tuple(parameters),
        optional_parameters=tuple(optional),
        input_schema_json=json.dumps(schema, sort_keys=True),
        manifest_sha256=hashlib.sha256(raw).hexdigest(),
        provenance="Installed CLI manifest",
    )
    return spec, _factory(tool_id, description, argv, parameters, optional, limits, output_limit)


def render(argv, arguments):
    rendered = []
    for part in argv:
        match = PLACEHOLDER.fullmatch(part)
        if match:
            value = arguments[match.group(1)]
            if any(char in value for char in "\n\r\0"):
                raise ValueError(f"{match.group(1)} must be a single line")
            rendered.append(shlex.quote(value))
            continue
        if not STATIC.fullmatch(part):
            raise ValueError("CLI argument rejected")
        rendered.append(shlex.quote(part))
    command = " ".join(rendered)
    if len(command) > 8000:
        raise ValueError("CLI command exceeds the length limit")
    return command


def _factory(tool_id, description, argv, parameters, optional, limits, output_limit):
    def factory(context):
        async def invoke(**kwargs):
            for key, value in kwargs.items():
                if not isinstance(value, str):
                    return f"{key} must be text"
                if len(value) > limits[key]:
                    return f"{key} exceeds {limits[key]} characters"
            try:
                command = render(argv, kwargs)
            except ValueError as exc:
                return str(exc)

            async def execute():
                result = await context.sandbox.run_command(command)
                text = result.text()
                if len(text) > output_limit:
                    text = text[:output_limit] + "\n[truncated]"
                return ActionResult(result.ok, text, command=result)

            outcome = await context.action(f"cli.{tool_id}", {"command": command}, command, execute)
            return outcome.text

        return bind_parameters(tool_id, description, tuple(parameters), set(optional), invoke)

    return factory


def _parameters(value, path):
    if not isinstance(value, dict) or len(value) > 16:
        raise RuntimeError(f"{path.name}: declare at most 16 parameters")
    parameters, optional, limits = {}, [], {}
    for name, spec in value.items():
        if not IDENT.fullmatch(name) or not isinstance(spec, dict):
            raise RuntimeError(f"{path.name}: invalid parameter {name}")
        required = spec.get("required", True)
        limit = spec.get("max_length", 8000)
        description = spec.get("description", name)
        if (
            type(required) is not bool
            or type(limit) is not int
            or not 1 <= limit <= 8000
            or not isinstance(description, str)
            or not description
            or len(description) > 400
        ):
            raise RuntimeError(f"{path.name}: invalid parameter {name}")
        parameters[name] = description
        limits[name] = limit
        if not required:
            optional.append(name)
    return parameters, optional, limits


def _check_placeholders(argv, parameters, path):
    used = set()
    for part in argv:
        match = PLACEHOLDER.fullmatch(part)
        if match:
            if match.group(1) not in parameters:
                raise RuntimeError(f"{path.name}: unknown placeholder {part}")
            used.add(match.group(1))
        elif not STATIC.fullmatch(part):
            raise RuntimeError(f"{path.name}: static argument contains shell syntax: {part}")
    missing = set(parameters) - used
    if missing:
        raise RuntimeError(f"{path.name}: unused parameters: {', '.join(sorted(missing))}")


def _text(data, key, path):
    value = data.get(key)
    if not isinstance(value, str) or not value.strip() or len(value) > 2000:
        raise RuntimeError(f"{path.name}: {key} must be short text")
    return value.strip()
