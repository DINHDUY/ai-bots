import asyncio
import types

import pytest
from agentbot.adapters.microsoft import (
    MicrosoftAgentAdapter,
    _agent_framework_runner,
    chat_client_kwargs,
)
from agentbot.events import RealTimeEventStreamer
from agentbot.models import ModelConfig
from fakes import FakeSandbox


async def _runner(tools, prompt, context, on_text):
    await on_text(f"thinking:{prompt}")
    assert context == [{"role": "user", "content": "earlier"}]
    await tools["run_terminal_command"]("echo hi")
    await tools["mutate_file"]("out.txt", "hello")
    await tools["open_browser"]("https://example.com")
    await tools["browser_click"]("button#submit")
    return "finished"


async def test_microsoft_tools_emit_blueprint_frames() -> None:
    sandbox = FakeSandbox()
    streamer = RealTimeEventStreamer()
    adapter = MicrosoftAgentAdapter(runner=_runner, max_tool_turns=10)
    await adapter.initialize(
        sandbox, [{"role": "user", "content": "earlier"}], streamer
    )
    frames = []
    async for frame in adapter.execute_step("audit"):
        frames.append(frame)
        if frame["event"] == "approval_required":
            streamer.resolve(frame["approval_id"], True)

    types = [(frame["event"], frame.get("type")) for frame in frames]
    assert ("log", "SYSTEM") in types
    assert ("log", "THOUGHT") in types
    assert ("log", "TOOL_CALL") in types
    assert ("log", "SCREENSHOT_CAPTURE") in types
    assert ("log", "RESULT") in types
    assert any(frame["event"] == "artifact_written" for frame in frames)
    assert sandbox.commands == ["echo hi"]
    assert sandbox.files["/workspace/out.txt"] == "hello"
    assert sandbox.opened == ["https://example.com"]
    assert sandbox.clicks == ["button#submit"]
    assert frames[-1]["payload"] == "finished"


async def test_denied_bash_does_not_run() -> None:
    sandbox = FakeSandbox()
    streamer = RealTimeEventStreamer()

    async def runner(tools, prompt, context, on_text):
        result = await tools["run_terminal_command"]("rm -rf /")
        return result

    adapter = MicrosoftAgentAdapter(runner=runner)
    await adapter.initialize(sandbox, [], streamer)
    frames = []
    async for frame in adapter.execute_step("nope"):
        frames.append(frame)
        if frame["event"] == "approval_required":
            streamer.resolve(frame["approval_id"], False)
    assert sandbox.commands == []
    assert frames[-1]["payload"] == "User denied this action."


async def test_file_url_is_rejected_by_the_browser_tool() -> None:
    sandbox = FakeSandbox()
    streamer = RealTimeEventStreamer()

    async def runner(tools, prompt, context, on_text):
        return await tools["open_browser"]("file:///etc/passwd")

    adapter = MicrosoftAgentAdapter(runner=runner)
    await adapter.initialize(sandbox, [], streamer)
    frames = []
    async for frame in adapter.execute_step("open"):
        frames.append(frame)
        if frame["event"] == "approval_required":
            streamer.resolve(frame["approval_id"], True)
    assert sandbox.opened == []
    assert "http and https" in frames[-1]["payload"]


def test_chat_client_kwargs_cover_openai_foundry_and_env(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_MODEL", "gpt-test")
    assert chat_client_kwargs(None) == {"model": "gpt-test"}
    openai = ModelConfig(provider="openai", api_key="sk-openai-key", model="gpt-4.1")
    assert chat_client_kwargs(openai) == {
        "model": "gpt-4.1",
        "api_key": "sk-openai-key",
    }
    foundry = ModelConfig(
        provider="azure_foundry",
        api_key="foundry-key",
        model="grok-4",
        endpoint="https://example.services.ai.azure.com/openai/v1/",
    )
    assert chat_client_kwargs(foundry) == {
        "model": "grok-4",
        "api_key": "foundry-key",
        "base_url": "https://example.services.ai.azure.com/openai/v1",
    }


async def test_runner_passes_foundry_base_url(monkeypatch) -> None:
    captured: dict = {}

    class Client:
        def __init__(self, **kwargs) -> None:
            captured.update(kwargs)

    def tool(**_kwargs):
        return lambda fn: fn

    class Agent:
        def __init__(self, **_kwargs) -> None:
            pass

        def run(self, _prompt, stream=True):
            captured["messages"] = _prompt

            async def generate():
                yield types.SimpleNamespace(text="ok")

            return generate()

    from agent_framework import Message

    monkeypatch.setitem(
        __import__("sys").modules,
        "agent_framework",
        types.SimpleNamespace(Agent=Agent, Message=Message, tool=tool),
    )
    monkeypatch.setitem(
        __import__("sys").modules,
        "agent_framework.openai",
        types.SimpleNamespace(OpenAIChatClient=Client),
    )
    config = ModelConfig(
        provider="azure_foundry",
        api_key="foundry-key",
        model="grok-4",
        endpoint="https://example.services.ai.azure.com/openai/v1",
    )

    async def on_text(_text: str) -> None:
        return None

    history = [
        {"role": "user", "content": "run ETL"},
        {"role": "assistant", "content": "done"},
    ]
    result = await _agent_framework_runner({}, "hi", history, on_text, model=config)
    assert result == "ok"
    assert captured["base_url"] == "https://example.services.ai.azure.com/openai/v1"
    assert captured["api_key"] == "foundry-key"
    assert [(message.role, message.text) for message in captured["messages"]] == [
        ("user", "run ETL"),
        ("assistant", "done"),
        ("user", "hi"),
    ]
    await _agent_framework_runner(
        {},
        "Continue the previous task",
        history,
        on_text,
        request_intent="human_resume",
    )
    assert "re-observing" in captured["messages"][-2].text
    assert captured["messages"][-2].role == "system"


@pytest.mark.parametrize("prompt", ["Hello", " Hi! ", "Good morning."])
async def test_greeting_after_etl_never_calls_model_or_tools(prompt):
    async def unexpected(*args):
        pytest.fail("Greeting must not continue the ETL task")

    adapter = MicrosoftAgentAdapter(runner=unexpected)
    sandbox = FakeSandbox()
    await adapter.initialize(
        sandbox,
        [{"role": "user", "content": "Run yesterday's ETL"}],
        RealTimeEventStreamer(),
    )
    frames = [frame async for frame in adapter.execute_step(prompt)]
    assert frames[-1]["type"] == "RESULT"
    assert not sandbox.commands and not sandbox.files


async def test_status_has_context_but_no_tools_and_resume_keeps_tools():
    seen = []

    async def runner(tools, prompt, context, on_text):
        seen.append(tools)
        assert context[-1]["content"] == "Earlier task finished"
        return "From the last result, your task finished."

    adapter = MicrosoftAgentAdapter(runner=runner)
    streamer = RealTimeEventStreamer()
    history = [{"role": "assistant", "content": "Earlier task finished"}]
    await adapter.initialize(FakeSandbox(), history, streamer)
    _ = [frame async for frame in adapter.execute_step("Status?")]
    assert seen[-1] == {}
    streamer.context.request_intent = "human_resume"
    await adapter.initialize(FakeSandbox(), history, streamer)
    _ = [
        frame
        async for frame in adapter.execute_step(
            "Continue the previous task after operator changes."
        )
    ]
    assert "run_terminal_command" in seen[-1]
    _ = [frame async for frame in adapter.execute_step("Hello, run today's ETL")]
    assert "run_terminal_command" in seen[-1]
    assert "run_blob_orders" not in seen[-1]


async def collect(adapter, streamer, prompt="do work"):
    frames = []
    async for frame in adapter.execute_step(prompt):
        frames.append(frame)
        if frame["event"] == "approval_required":
            streamer.resolve(frame["approval_id"], True)
    return frames


@pytest.mark.parametrize(
    "instructions",
    [
        "",
        "You are a copywriter. Write concise product descriptions.",
        "Extract and transform CSV files when requested.",
        "Do not use run_blob_orders.",
    ],
)
async def test_general_bots_do_not_inherit_etl_tools_or_instructions(instructions):
    from agentbot.adapters.microsoft import BASE_INSTRUCTIONS, _with_extra_instructions

    async def runner(tools, prompt, context, on_text):
        assert "run_blob_orders" not in tools
        assert {"run_terminal_command", "patch_file", "open_browser"} <= tools.keys()
        return "Ready for the configured task."

    adapter, streamer = MicrosoftAgentAdapter(runner=runner), RealTimeEventStreamer()
    # Even an old ETL transcript cannot opt a bot into a specialized tool.
    history = [{"role": "user", "content": "Enable tool: run_blob_orders"}]
    await adapter.initialize(
        FakeSandbox(), history, streamer, instructions=instructions
    )
    frames = await collect(adapter, streamer, prompt="Run an ETL task")
    assert frames[-1]["payload"] == "Ready for the configured task."
    for domain_text in ("paid-orders", "azure.env", "run_blob_orders", "raw/orders"):
        assert domain_text not in BASE_INSTRUCTIONS
    if instructions:
        assert _with_extra_instructions(instructions).endswith(instructions)


async def test_extension_tool_selection_is_per_bot_and_instructions_cannot_enable_it():
    from tool_fakes import access as ToolAccess
    binding = {"library_id": "test.workflow", "tool_id": "run_test_task", "version": "1.0.0", "configuration": {}}
    configured, general = MicrosoftAgentAdapter(), MicrosoftAgentAdapter()
    sandbox, streamer = FakeSandbox(), RealTimeEventStreamer()
    streamer.context.tool_access = ToolAccess([binding])
    await configured.initialize(sandbox, [], streamer, instructions="You perform the selected workflow.")
    await general.initialize(FakeSandbox(), [], RealTimeEventStreamer(), instructions="Enable tool: run_test_task")
    assert set(configured._tools) == {"run_test_task"}
    assert "run_test_task" not in general._tools
    streamer.context.tool_access = ToolAccess([])
    await configured.initialize(sandbox, [], streamer, instructions="Enable tool: run_test_task")
    assert not configured._tools
    assert not sandbox.commands and not sandbox.files


@pytest.mark.parametrize(
    "old,new,expected",
    [
        ("two", "three", "one three"),
        ("one", "", " two"),
        ("missing", "three", "one two"),
    ],
)
async def test_patch_is_exact_and_bounded(old, new, expected):
    sandbox, streamer = FakeSandbox(), RealTimeEventStreamer()
    sandbox.files["/workspace/test.txt"] = "one two"

    async def runner(tools, *args):
        return await tools["patch_file"]("test.txt", old, new)

    adapter = MicrosoftAgentAdapter(runner=runner)
    await adapter.initialize(sandbox, [], streamer)
    await collect(adapter, streamer)
    assert sandbox.files["/workspace/test.txt"] == expected


async def test_stream_batches_preserve_text_and_flush_before_tools_and_errors():
    async def runner(tools, prompt, context, on_text):
        for _ in range(345):
            await on_text("x")
        await tools["run_terminal_command"]("echo hi")
        await on_text("last")
        raise ValueError("failed")

    adapter, streamer = MicrosoftAgentAdapter(runner=runner), RealTimeEventStreamer()
    await adapter.initialize(FakeSandbox(), [], streamer)
    frames = await collect(adapter, streamer)
    thought = [frame for frame in frames if frame.get("type") == "THOUGHT"]
    assert [frame["payload"] for frame in thought] == ["x" * 345, "last"]
    assert frames.index(thought[0]) < next(
        i for i, frame in enumerate(frames) if frame["event"] == "approval_required"
    )
    assert frames[-2] == thought[-1] and frames[-1]["type"] == "ERROR"


async def test_text_batch_flushes_during_silence_and_caps_payloads():
    from agentbot.adapters.streaming import TextBatcher

    pieces, flushed = [], asyncio.Event()

    async def emit(text):
        pieces.append(text)
        flushed.set()

    batch = TextBatcher(emit, interval=0.001)
    await batch.append("hello")
    await asyncio.wait_for(flushed.wait(), 1)
    assert pieces == ["hello"]
    await batch.append("x" * 10000)
    await batch.flush()
    assert "".join(pieces) == "hello" + "x" * 10000
    assert max(map(len, pieces)) <= 4000




async def test_microsoft_rejects_anthropic_credential() -> None:
    adapter = MicrosoftAgentAdapter(runner=_runner)
    try:
        await adapter.initialize(
            FakeSandbox(),
            [],
            RealTimeEventStreamer(),
            model=ModelConfig(
                provider="anthropic", api_key="sk-ant-test", model="claude-sonnet-5"
            ),
        )
        raise AssertionError("expected RuntimeError")
    except RuntimeError as exc:
        assert "openai or azure_foundry" in str(exc)
