"""CLI manifests and allowlisted entry points join the composed catalog."""

import hashlib
import json
import shlex
from dataclasses import replace
from types import SimpleNamespace

import pytest
from agentbot.interfaces import ActionResult
from agentbot.tools.context import ToolExecutionContext
from agentbot.tools.registry import ToolSpec
from agentbot_tools.catalog import load_catalog
from agentbot_tools.cli import parse_manifest, render


def _manifest(path, argv='["date"]', extra=""):
    path.write_text(
        f"""
tool_id = "show_date"
name = "Show date"
description = "Show the computer clock."
binary = "date"
argv = {argv}
{extra}
""".strip(),
        encoding="utf-8",
    )
    return path


async def test_manifest_quotes_values_and_rejects_shell_syntax(tmp_path):
    path = _manifest(
        tmp_path / "show_date.toml",
        argv='["date", "{when}"]',
        extra='[parameters.when]\ndescription = "Clock format"\nrequired = true\nmax_length = 20\n',
    )
    spec, factory = parse_manifest(path)
    assert render(["date", "{when}"], {"when": "; rm -rf /"}) == "date " + "'; rm -rf /'"
    before = spec.digest
    path.write_text(
        path.read_text(encoding="utf-8").replace("Show date", "Show the date"), encoding="utf-8"
    )
    changed, _factory = parse_manifest(path)
    assert changed.digest != before
    broken = tmp_path / "broken.toml"
    broken.write_text(
        path.read_text(encoding="utf-8").replace('"{when}"', '"; rm"'), encoding="utf-8"
    )
    with pytest.raises(RuntimeError, match="shell syntax"):
        parse_manifest(broken)
    sandbox_commands = []

    async def run_command(command):
        sandbox_commands.append(command)
        from agentbot.interfaces import CommandResult

        return CommandResult("1", 0, stdout="ok")

    async def action(_operation, _arguments, _detail, execute):
        return await execute()

    async def unused(_command):
        raise AssertionError("CLI tools do not use the generic shell helper")

    tool = factory(
        ToolExecutionContext(SimpleNamespace(run_command=run_command), action, unused)
    )
    assert await tool(when="+%Y") == "ok"
    assert sandbox_commands == ["date " + shlex.quote("+%Y")]


def test_allowlist_loads_named_plugin_and_ignores_others(tmp_path, monkeypatch):
    module = tmp_path / "plugin_demo_mod.py"
    module.write_text("VALUE = 1\n", encoding="utf-8")
    monkeypatch.syspath_prepend(str(tmp_path))
    record = "plugin_demo_mod.py,sha256=abc,1\n"
    digest = hashlib.sha256(record.encode()).hexdigest()
    spec = ToolSpec(
        "plugin.demo_tools.echo",
        "Demo",
        "echo_text",
        "Echo",
        "Return text.",
        ("microsoft",),
        ("echo",),
        parameters=("text",),
    )

    def factory(_context):
        async def echo_text(text: str) -> str:
            return text

        return echo_text

    class Dist:
        def __init__(self, name):
            self.metadata = {"Name": name}
            self.version = "1.2.0"

        def read_text(self, filename):
            assert filename == "RECORD"
            return record

    class Entry:
        def __init__(self, name):
            self.dist = Dist(name)
            self.value = "plugin_demo_mod:plugin"

        def load(self):
            if self.dist.metadata["Name"] != "demo-tools":
                raise AssertionError("unlisted plugin was loaded")
            return lambda: {"specs": (spec,), "factories": {"echo_text": factory}}

    def entry_points(*, group):
        assert group == "agentbot.tools"
        return [Entry("demo-tools"), Entry("other-tools")]

    monkeypatch.setattr("importlib.metadata.entry_points", entry_points)
    monkeypatch.setattr("importlib.metadata.distribution", lambda name: Dist(name))
    allowlist = tmp_path / "allow.json"
    allowlist.write_text(
        json.dumps(
            {
                "plugins": [
                    {"distribution": "demo-tools", "version": "1.2.0", "record_sha256": digest}
                ]
            }
        ),
        encoding="utf-8",
    )
    catalog = load_catalog(allowlist=str(allowlist))
    loaded = catalog.specs["plugin.demo_tools.echo/echo_text"]
    assert loaded.provenance == "Installed plugin demo-tools==1.2.0"
    assert loaded.digest
    assert "echo_text" in catalog.factories
    assert "other-tools" not in {item.distribution for item in catalog.specs.values()}
    allowlist.write_text(
        json.dumps(
            {
                "plugins": [
                    {
                        "distribution": "demo-tools",
                        "version": "1.2.0",
                        "record_sha256": "0" * 64,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(RuntimeError, match="RECORD hash"):
        load_catalog(allowlist=str(allowlist))
    bad = replace(spec, library_id="tools.echo")

    class BadEntry(Entry):
        def load(self):
            return lambda: {"specs": (bad,), "factories": {"echo_text": factory}}

    monkeypatch.setattr(
        "importlib.metadata.entry_points",
        lambda *, group: [BadEntry("demo-tools")],
    )
    allowlist.write_text(
        json.dumps(
            {
                "plugins": [
                    {"distribution": "demo-tools", "version": "1.2.0", "record_sha256": digest}
                ]
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(RuntimeError, match="library id"):
        load_catalog(allowlist=str(allowlist))


async def test_plugin_action_uses_the_declared_operation():
    spec = ToolSpec(
        "plugin.demo_tools.echo",
        "Demo",
        "echo_text",
        "Echo",
        "Return text.",
        ("microsoft",),
        ("echo",),
        parameters=("text",),
        distribution="demo-tools",
        implementation_modules=("agentbot_tools.plugins",),
        provenance="Installed plugin demo-tools==1.2.0",
    )

    def factory(context):
        async def echo_text(text: str) -> str:
            async def execute():
                return ActionResult(True, text)

            result = await context.action("echo", {"text": text}, text, execute)
            return result.text

        return echo_text

    from agentbot.tools.catalog import ToolCatalog

    access = ToolCatalog({spec.key: spec}, {spec.tool_id: factory}).access(
        [
            {
                "library_id": spec.library_id,
                "tool_id": spec.tool_id,
                "version": spec.version,
                "configuration": {},
            }
        ]
    )
    seen = []

    async def action(operation, arguments, detail, execute):
        seen.append((operation, arguments, detail))
        with access.scope(spec.tool_id, arguments):
            return await execute()

    tool = access.wrap(spec.tool_id, factory(ToolExecutionContext(object(), action, None)))
    assert await tool(text="hello") == "hello"
    assert seen == [("echo", {"text": "hello"}, "hello")]
