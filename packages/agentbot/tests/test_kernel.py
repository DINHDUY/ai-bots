from pathlib import Path

from agentbot.events import RealTimeEventStreamer
from agentbot.kernel import EngineRuntimeManager, SessionStore
from agentbot.registry import FrameworkRegistry
from fakes import MemorySessions


class EchoAdapter:
    def __init__(self) -> None:
        self.seen_context: list[dict] = []

    async def initialize(self, sandbox, memory_context, state_streamer, instructions: str = "", model=None) -> None:
        self.seen_context = list(memory_context)
        self.streamer = state_streamer
        self.model = model

    def execute_step(self, prompt: str):
        return self._run(prompt)

    async def _run(self, prompt: str):
        yield self.streamer.emit_log("echo", "RESULT", f"echo:{prompt}")


def _kernel(tmp_path: Path) -> tuple[EngineRuntimeManager, MemorySessions, list[EchoAdapter]]:
    created: list[EchoAdapter] = []

    def factory() -> EchoAdapter:
        adapter = EchoAdapter()
        created.append(adapter)
        return adapter

    registry = FrameworkRegistry()
    registry.register_framework("echo", factory)
    sessions = MemorySessions()
    kernel = EngineRuntimeManager(registry, sessions, SessionStore(tmp_path))
    return kernel, sessions, created


async def _run(kernel: EngineRuntimeManager, prompt: str, session_id: str = "sess-1") -> list[dict]:
    streamer = RealTimeEventStreamer()
    return [
        frame
        async for frame in kernel.process_agent_request("echo", prompt, session_id, streamer)
    ]


async def test_session_sandbox_is_reused_and_memory_is_appended(tmp_path: Path) -> None:
    kernel, sessions, created = _kernel(tmp_path)
    first = await _run(kernel, "one")
    second = await _run(kernel, "two")
    assert first[-1]["payload"] == "echo:one"
    assert second[-1]["payload"] == "echo:two"
    assert sessions.created == 1
    assert created[1].seen_context == [
        {"role": "user", "content": "one"},
        {"role": "assistant", "content": "echo:one"},
    ]
    stored = SessionStore(tmp_path).load("sess-1")
    assert stored[-1]["content"] == "echo:two"


async def test_unknown_framework_and_bad_session_id_fail(tmp_path: Path) -> None:
    kernel, _sessions, _created = _kernel(tmp_path)
    streamer = RealTimeEventStreamer()
    try:
        async for _frame in kernel.process_agent_request("nope", "hi", "sess-1", streamer):
            pass
        raise AssertionError("expected ValueError")
    except ValueError as exc:
        assert "could not be resolved" in str(exc)

    try:
        async for _frame in kernel.process_agent_request("echo", "hi", "../etc", streamer):
            pass
        raise AssertionError("expected ValueError")
    except ValueError as exc:
        assert "session_id" in str(exc)


async def test_idle_close_removes_the_sandbox(tmp_path: Path) -> None:
    kernel, sessions, _created = _kernel(tmp_path)
    now = {"t": 0.0}
    kernel._clock = lambda: now["t"]
    await _run(kernel, "one", "idle-1")
    now["t"] = 100.0
    closed = await kernel.close_idle(30)
    assert closed == ["idle-1"]
    assert sessions.closed == ["idle-1"]
