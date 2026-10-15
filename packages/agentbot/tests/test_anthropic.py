import types

from agentbot.adapters.anthropic import (
    HALT_TEXT,
    AnthropicMessagesClient,
    ClaudeAgentAdapter,
    ModelTurn,
    ToolUse,
)
from agentbot.events import RealTimeEventStreamer
from agentbot.models import ModelConfig
from fakes import FakeSandbox


class ScriptedClient:
    def __init__(self, turns: list[ModelTurn]) -> None:
        self.turns = list(turns)
        self.calls: list[list[dict]] = []

    async def complete(self, *, messages, system):
        self.calls.append(messages)
        return self.turns.pop(0)


def _use(tool_id: str, name: str, payload: dict, toolset: str | None = None) -> ToolUse:
    return ToolUse(id=tool_id, name=name, toolset_name=toolset, input=payload)


async def _collect(adapter: ClaudeAgentAdapter, streamer: RealTimeEventStreamer, decision: bool = True):
    frames = []
    async for frame in adapter.execute_step("do the task"):
        frames.append(frame)
        if frame["event"] == "approval_required":
            streamer.resolve(frame["approval_id"], decision)
    return frames


async def test_failed_computer_action_halts_the_rest_of_the_batch() -> None:
    sandbox = FakeSandbox()
    sandbox.fail_actions.add("left_click")
    click = _use("c1", "left_click", {"coordinate": [10, 10]}, "computer")
    shot = _use("c2", "screenshot", {}, "computer")
    client = ScriptedClient(
        [
            ModelTurn(stop_reason="tool_use", text="clicking", tool_uses=[click, shot]),
            ModelTurn(stop_reason="end_turn", text="stopped", tool_uses=[]),
        ]
    )
    streamer = RealTimeEventStreamer()
    adapter = ClaudeAgentAdapter(client=client)
    await adapter.initialize(sandbox, [], streamer)
    frames = await _collect(adapter, streamer)

    assert [name for name, _params in sandbox.actions] == ["left_click"]
    results = client.calls[1][-1]["content"]
    assert results[0]["is_error"] is True
    assert results[0]["content"] == "left_click failed"
    assert results[1]["content"] == HALT_TEXT
    assert results[1]["toolset_name"] == "computer"
    assert frames[-1]["type"] == "RESULT"
    assert frames[-1]["payload"] == "stopped"


async def test_denied_action_does_not_reach_the_sandbox() -> None:
    sandbox = FakeSandbox()
    click = _use("c1", "left_click", {"coordinate": [1, 1]}, "computer")
    client = ScriptedClient(
        [
            ModelTurn(stop_reason="tool_use", text="click", tool_uses=[click]),
            ModelTurn(stop_reason="end_turn", text="done", tool_uses=[]),
        ]
    )
    streamer = RealTimeEventStreamer()
    adapter = ClaudeAgentAdapter(client=client)
    await adapter.initialize(sandbox, [], streamer)
    await _collect(adapter, streamer, decision=False)
    assert sandbox.actions == []
    assert client.calls[1][-1]["content"][0]["content"] == "User denied this action."


async def test_editor_create_replace_and_path_jail() -> None:
    sandbox = FakeSandbox()
    create = _use("e1", "str_replace_based_edit_tool", {"command": "create", "path": "note.txt", "file_text": "alpha"})
    replace = _use(
        "e2",
        "str_replace_based_edit_tool",
        {"command": "str_replace", "path": "note.txt", "old_str": "alpha", "new_str": "beta"},
    )
    escape = _use(
        "e3",
        "str_replace_based_edit_tool",
        {"command": "create", "path": "../etc/passwd", "file_text": "nope"},
    )
    view = _use("e4", "str_replace_based_edit_tool", {"command": "view", "path": "note.txt"})
    client = ScriptedClient(
        [
            ModelTurn(stop_reason="tool_use", text="edit", tool_uses=[create, replace]),
            ModelTurn(stop_reason="tool_use", text="view", tool_uses=[view, escape]),
            ModelTurn(stop_reason="end_turn", text="ok", tool_uses=[]),
        ]
    )
    streamer = RealTimeEventStreamer()
    adapter = ClaudeAgentAdapter(client=client)
    await adapter.initialize(sandbox, [{"role": "user", "content": "keep it small"}], streamer)
    frames = await _collect(adapter, streamer)

    assert sandbox.files["/workspace/note.txt"] == "beta"
    assert any(frame["event"] == "artifact_written" for frame in frames)
    view_result = client.calls[2][-1]["content"][0]["content"]
    assert "beta" in view_result
    escape_result = client.calls[2][-1]["content"][1]
    assert escape_result["is_error"] is True
    assert "/etc/passwd" not in sandbox.files


async def test_screenshot_does_not_require_approval() -> None:
    sandbox = FakeSandbox()
    shot = _use("c1", "screenshot", {}, "computer")
    client = ScriptedClient(
        [
            ModelTurn(stop_reason="tool_use", text="look", tool_uses=[shot]),
            ModelTurn(stop_reason="end_turn", text="seen", tool_uses=[]),
        ]
    )
    streamer = RealTimeEventStreamer()
    adapter = ClaudeAgentAdapter(client=client)
    await adapter.initialize(sandbox, [], streamer)
    frames = await _collect(adapter, streamer)
    assert not any(frame["event"] == "approval_required" for frame in frames)
    assert any(frame.get("type") == "SCREENSHOT_CAPTURE" for frame in frames)
    image_result = client.calls[1][-1]["content"][0]["content"]
    assert image_result[0]["type"] == "image"


async def test_initialize_keeps_a_scripted_client_and_applies_anthropic_keys() -> None:
    scripted = ScriptedClient([])
    kept = ClaudeAgentAdapter(client=scripted)
    config = ModelConfig(provider="anthropic", api_key="sk-ant-test", model="claude-sonnet-5")
    await kept.initialize(FakeSandbox(), [], RealTimeEventStreamer(), model=config)
    assert kept._client is scripted

    live = ClaudeAgentAdapter()
    await live.initialize(FakeSandbox(), [], RealTimeEventStreamer(), model=config)
    assert isinstance(live._client, AnthropicMessagesClient)
    assert live._client.api_key == "sk-ant-test"
    assert live._client.model == "claude-sonnet-5"

    rejected = ClaudeAgentAdapter()
    try:
        await rejected.initialize(
            FakeSandbox(),
            [],
            RealTimeEventStreamer(),
            model=ModelConfig(provider="openai", api_key="sk-openai-key", model="gpt-4.1"),
        )
        raise AssertionError("expected RuntimeError")
    except RuntimeError as exc:
        assert "anthropic" in str(exc)


async def test_messages_client_passes_the_api_key(monkeypatch) -> None:
    captured: dict = {}

    class Messages:
        async def create(self, **kwargs):
            captured["create"] = kwargs
            return types.SimpleNamespace(content=[], stop_reason="end_turn")

    class FakeAnthropic:
        def __init__(self, **kwargs) -> None:
            captured["init"] = kwargs
            self.messages = Messages()

    monkeypatch.setattr("anthropic.AsyncAnthropic", FakeAnthropic, raising=False)
    import anthropic

    monkeypatch.setattr(anthropic, "AsyncAnthropic", FakeAnthropic)
    client = AnthropicMessagesClient(model="claude-sonnet-5", api_key="sk-ant-test")
    turn = await client.complete(messages=[], system="be brief")
    assert turn.stop_reason == "end_turn"
    assert captured["init"] == {"api_key": "sk-ant-test"}
    assert captured["create"]["model"] == "claude-sonnet-5"
