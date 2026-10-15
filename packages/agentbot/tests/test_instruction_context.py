"""Long role instructions reach provider requests independently of history bounds."""

import types

from agentbot.adapters.anthropic import ClaudeAgentAdapter
from agentbot.adapters.microsoft import MicrosoftAgentAdapter
from agentbot.events import RealTimeEventStreamer
from fakes import FakeSandbox


async def test_microsoft_sends_16000_character_instructions(monkeypatch):
    captured = {}

    class Agent:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        async def run(self, messages, stream=True):
            yield types.SimpleNamespace(text="Done")

    monkeypatch.setattr("agent_framework.Agent", Agent)
    monkeypatch.setattr("agent_framework.openai.OpenAIChatClient", lambda **kwargs: object())
    body = "# Role\n" + "x" * 15990 + "END"
    adapter = MicrosoftAgentAdapter()
    await adapter.initialize(FakeSandbox(), [], RealTimeEventStreamer(), instructions=body)
    frames = [frame async for frame in adapter.execute_step("Perform the assigned task.")]
    assert frames[-1]["payload"] == "Done"
    assert body in captured["instructions"]


async def test_anthropic_sends_16000_character_instructions(monkeypatch):
    captured = {}

    class Messages:
        async def create(self, **kwargs):
            captured.update(kwargs)
            return types.SimpleNamespace(content=[], stop_reason="end_turn")

    monkeypatch.setattr(
        "anthropic.AsyncAnthropic",
        lambda **kwargs: types.SimpleNamespace(messages=Messages()),
    )
    body = "# Role\n" + "x" * 15990 + "END"
    adapter = ClaudeAgentAdapter()
    await adapter.initialize(FakeSandbox(), [], RealTimeEventStreamer(), instructions=body)
    frames = [frame async for frame in adapter.execute_step("Perform the assigned task.")]
    assert frames[-1]["type"] == "RESULT"
    assert body in captured["system"]
    assert captured["max_tokens"] == 4096
