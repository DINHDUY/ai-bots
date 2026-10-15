"""The manifest and wrappers cannot widen a run's available tools."""

from dataclasses import replace

import pytest
from agentbot.tools import ToolUnavailable
from agentbot.tools.registry import make_registry
from agentbot_tools.registry import REGISTRY as PRODUCT_REGISTRY
from tool_fakes import WORKFLOW
from tool_fakes import access as ToolAccess

REGISTRY = {**PRODUCT_REGISTRY, WORKFLOW.key: WORKFLOW}


def item(key, resource=None):
    spec = REGISTRY[key]
    return {
        "library_id": spec.library_id,
        "tool_id": spec.tool_id,
        "version": spec.version,
        "configuration": {"resource_id": resource} if resource else {},
    }


def test_registry_rejects_collisions_missing_dependencies_and_cycles():
    spec = REGISTRY["sandbox.terminal/run_terminal_command"]
    with pytest.raises(ValueError, match="Duplicate"):
        make_registry([spec, spec])
    with pytest.raises(ValueError, match="Unknown dependency"):
        make_registry([replace(spec, dependencies=("missing",))])
    with pytest.raises(ValueError, match="cycle"):
        make_registry([replace(spec, dependencies=(spec.key,))])
    assert len(spec.digest) == 64


def test_manifest_pins_extracted_adapter_modules(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from agentbot.tools import registry

    facade = tmp_path / "__init__.py"
    operation = tmp_path / "operation.py"
    facade.write_text("from .operation import execute\n", encoding="utf-8")
    operation.write_text("def execute(): return 1\n", encoding="utf-8")
    monkeypatch.setattr(
        registry,
        "find_spec",
        lambda _: SimpleNamespace(origin=str(facade), submodule_search_locations=[str(tmp_path)]),
    )
    spec = REGISTRY["sandbox.terminal/run_terminal_command"]
    before = replace(spec).digest
    operation.write_text("def execute(): return 2\n", encoding="utf-8")
    assert replace(spec).digest != before
    unchanged = replace(spec).digest
    (tmp_path / "ignored.pyc").write_bytes(b"cache")
    assert replace(spec).digest == unchanged
    (tmp_path / "additional.py").write_text("VALUE = 3\n", encoding="utf-8")
    assert replace(spec).digest != unchanged


def test_composite_scope_and_resource_selector_do_not_expand_access():
    access = ToolAccess(
        [
            item("test.workflow/run_test_task"),
            item("github.issues/github_issues", "owned"),
        ]
    )
    with pytest.raises(ToolUnavailable):
        access.operation("bash", {"command": "echo nope"})
    with access.scope("run_test_task"):
        assert access.operation("bash", {})["tool_id"] == "run_test_task"
        with pytest.raises(ToolUnavailable):
            access.operation("open_browser", {})
    with pytest.raises(ToolUnavailable):
        access.require("github_issues", {"connection_id": "foreign"})
    assert access.require("github_issues", {"connection_id": "owned"})
    with access.scope("github_issues", {"connection_id": "owned"}):
        with pytest.raises(ToolUnavailable):
            access.operation("connector.github", {"connection_id": "foreign"})
    with pytest.raises(ToolUnavailable):
        ToolAccess([item("github.issues/github_issues")]).require("github_issues")


async def test_anthropic_rejects_unselected_native_tools_before_dispatch():
    from agentbot.adapters.anthropic import EDITOR_NAME, ClaudeAgentAdapter, ToolUse
    from agentbot.events import RealTimeEventStreamer

    streamer = RealTimeEventStreamer()
    streamer.context.tool_access = ToolAccess([])
    adapter = ClaudeAgentAdapter()
    await adapter.initialize(object(), [], streamer)
    for name in ("bash", EDITOR_NAME, "screenshot", "left_click"):
        with pytest.raises(ToolUnavailable):
            await adapter._dispatch(ToolUse("id", name, None, {}))
    assert not adapter._client.tool_access.bindings


async def test_ufo_requires_bundle_before_touching_companion():
    from agentbot.events import RealTimeEventStreamer
    from agentbot.models import ModelConfig
    from agentbot_tools.ufo import UfoAgentAdapter

    streamer = RealTimeEventStreamer()
    streamer.context.tool_access = ToolAccess([])
    adapter = UfoAgentAdapter()
    await adapter.initialize(
        object(),
        [],
        streamer,
        model=ModelConfig(provider="openai", model="test", api_key="test-key-valid"),
    )
    with pytest.raises(ToolUnavailable, match="windows_desktop"):
        await anext(adapter.execute_step("Observe Windows"))


async def test_microsoft_library_wrapper_keeps_sdk_function_schema():
    from agent_framework import tool
    from agentbot.adapters.microsoft import MicrosoftAgentAdapter
    from agentbot.events import RealTimeEventStreamer

    streamer = RealTimeEventStreamer()
    streamer.context.tool_access = ToolAccess([item("test.workflow/run_test_task")])
    adapter = MicrosoftAgentAdapter()
    await adapter.initialize(object(), [], streamer)
    function = tool(name="run_test_task")(adapter._tools["run_test_task"])
    schema = function.parameters()
    assert "message" in schema["properties"] and "context" not in schema["properties"]


async def test_anthropic_advertises_only_selected_native_bundle(monkeypatch):
    from types import SimpleNamespace

    import anthropic
    from agentbot.adapters.anthropic import AnthropicMessagesClient

    requests = []

    async def create(**kwargs):
        requests.append(kwargs)
        return SimpleNamespace(content=[], stop_reason="end_turn")

    monkeypatch.setattr(
        anthropic,
        "AsyncAnthropic",
        lambda **kw: SimpleNamespace(messages=SimpleNamespace(create=create)),
    )
    client = AnthropicMessagesClient(api_key="test")
    client.tool_access = ToolAccess([item("sandbox.terminal/run_terminal_command")])
    await client.complete(messages=[], system="General assistant")
    assert requests[0]["tools"] == [{"type": "bash_20250124", "name": "bash"}]
    client.tool_access = ToolAccess([])
    await client.complete(messages=[], system="General assistant")
    assert requests[1]["tools"] == []
