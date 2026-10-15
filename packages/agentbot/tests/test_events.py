import asyncio

from agentbot.events import RealTimeEventStreamer


def test_log_and_artifact_frames_match_the_blueprint() -> None:
    streamer = RealTimeEventStreamer()
    log = streamer.emit_log("engine", "THOUGHT", "hello")
    artifact = streamer.emit_artifact("engine", "./build/output.log", "Build complete.")
    assert log == {"event": "log", "source": "engine", "type": "THOUGHT", "payload": "hello"}
    assert artifact["event"] == "artifact_written"
    assert artifact["meta"]["path"] == "./build/output.log"


async def test_approval_timeout_denies() -> None:
    streamer = RealTimeEventStreamer(approval_timeout=0.01)
    _frame, future = streamer.begin_approval("engine", "bash", "rm -rf /")
    assert await streamer.wait_for_approval(future) is False


async def test_approval_resolve_before_wait() -> None:
    streamer = RealTimeEventStreamer()
    frame, future = streamer.begin_approval("engine", "bash", "ls")
    streamer.resolve(frame["approval_id"], True)
    assert await streamer.wait_for_approval(future) is True


async def test_late_approval_unblocks_the_waiter() -> None:
    streamer = RealTimeEventStreamer(approval_timeout=1)
    frame, future = streamer.begin_approval("engine", "bash", "ls")

    async def decide() -> None:
        await asyncio.sleep(0.01)
        streamer.resolve(frame["approval_id"], False)

    asyncio.create_task(decide())
    assert await streamer.wait_for_approval(future) is False
