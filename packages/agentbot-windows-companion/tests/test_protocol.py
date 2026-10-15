import asyncio
import json
import sys
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from agentbot_windows.protocol import Permit, WindowsAction
from agentbot_windows.service import Companion, Worker, WorkerStopped
from agentbot_windows.state import LocalState, ReceiptJournal
from pydantic import ValidationError


def permit():
    return Permit(
        action_id="action-123",
        session_id="session-123",
        generation=1,
        epoch="epoch-123",
        local_revision=1,
        expires_at=time.time() + 8,
        action=WindowsAction(
            function="set_edit_text",
            observation_id="observe-123",
            window_id="10",
            control_id="2",
            arguments={"text": "hello"},
        ),
    ).sign("secret")


@pytest.mark.parametrize(
    "change", ["argument", "expired", "epoch", "revision", "signature"]
)
def test_permit_fences_changes(change):
    p = permit()
    epoch, revision = "epoch-123", 1
    if change == "argument":
        p.action.arguments["text"] = "changed"
    if change == "expired":
        p.expires_at = time.time() - 1
        p.sign("secret")
    if change == "epoch":
        epoch = "epoch-new"
    if change == "revision":
        revision = 2
    if change == "signature":
        p.signature = "bad"
    with pytest.raises(ValueError):
        p.verify("secret", epoch, revision)


@pytest.mark.parametrize(
    "function,arguments",
    [
        ("shell", {"command": "calc"}),
        ("launch_app", {"app": "powershell"}),
        ("set_edit_text", {"text": "hello", "clear_current_text": True}),
        ("keyboard_input", {"keys": "{ENTER 10000000}"}),
        ("keyboard_input", {"keys": "^a{DELETE}"}),
        ("keyboard_input", {"keys": "{VK_CONTROL down}"}),
        ("click_on_coordinates", {"x": float("nan"), "y": 0}),
        ("click_on_coordinates", {"x": 1.1, "y": 0}),
        ("wheel_mouse_input", {"wheel_dist": 11}),
    ],
)
def test_only_bounded_actions(function, arguments):
    with pytest.raises(ValidationError):
        WindowsAction(
            function=function,
            arguments=arguments,
            observation_id="observe-123",
            window_id="1",
        )


def test_receipt_survives_crash_and_never_replays(tmp_path):
    path = tmp_path / "receipts.sqlite"
    first = ReceiptJournal(path)
    assert first.claim(permit()) is None
    first.close()
    recovered = ReceiptJournal(path)
    assert recovered.claim(permit())["outcome_unknown"]
    changed = permit()
    changed.action.arguments["text"] = "different"
    with pytest.raises(RuntimeError):
        recovered.claim(changed)
    recovered.finish("action-123", {"ok": True, "effect_observed": True})
    assert recovered.claim(permit())["effect_observed"]
    recovered.close()


async def test_queued_worker_request_cannot_restart_after_stop(tmp_path):
    worker = Worker(tmp_path, "desktop")
    await worker.lock.acquire()
    waiting = asyncio.create_task(worker.call("execute"))
    await asyncio.sleep(0)
    await worker.stop("Physical mouse input; agent paused")
    worker.lock.release()
    with pytest.raises(WorkerStopped, match="before dispatch: Physical mouse input") as stopped:
        await waiting
    assert not stopped.value.dispatched
    assert worker.process is None


async def test_stop_during_worker_spawn_preserves_reason_and_never_dispatches(tmp_path, monkeypatch):
    worker = Worker(tmp_path, "planner")
    spawning, finish_spawn = asyncio.Event(), asyncio.Event()
    process = SimpleNamespace(
        pid=123, returncode=None, stdin=Mock(), stdout=Mock(),
        kill=Mock(), wait=AsyncMock(),
    )
    job = SimpleNamespace(Close=Mock())

    async def spawn(*args, **kwargs):
        spawning.set()
        await finish_spawn.wait()
        return process

    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    monkeypatch.setattr("agentbot_windows.win_session.worker_job", lambda pid: job)
    request = asyncio.create_task(worker.call("planner", {"operation": "start"}))
    await spawning.wait()
    await worker.stop("Physical keyboard input; agent paused")
    finish_spawn.set()
    with pytest.raises(WorkerStopped, match="before dispatch: Physical keyboard input") as stopped:
        await request
    assert not stopped.value.dispatched
    process.stdin.write.assert_not_called()
    process.kill.assert_called_once()
    process.wait.assert_awaited_once()
    assert worker.process is None


async def test_interrupted_response_reports_pause_before_error(tmp_path, monkeypatch):
    c = Companion(
        {"name": "Test", "token": "secret"}, tmp_path, tmp_path / "r.sqlite",
        session_check=lambda: (True, "test:1", ""),
    )
    c.state.change(sharing=True, armed=True)

    async def interrupted(*args, **kwargs):
        await c.local_stop("Physical mouse input; agent paused")
        raise WorkerStopped(c.state.reason)

    monkeypatch.setattr(c.planner, "call", interrupted)
    ws = SimpleNamespace(send=AsyncMock())
    try:
        await c.handle(
            {"id": "start", "method": "planner", "arguments": {"operation": "start"}},
            ws, asyncio.Lock(), asyncio.Lock(),
        )
        messages = [json.loads(call.args[0]) for call in ws.send.await_args_list]
        assert len(messages) == 2
        assert messages[0]["type"] == "status"
        assert messages[0]["state"]["sharing"]
        assert not messages[0]["state"]["armed"]
        assert messages[0]["state"]["reason"] == "Physical mouse input; agent paused"
        assert messages[1]["id"] == "start"
        assert "Physical mouse input" in messages[1]["error"]
        assert not c.automating
    finally:
        c.journal.close()


async def test_companion_off_expired_and_local_stop(tmp_path):
    c = Companion(
        {"name": "Test", "token": "secret"},
        tmp_path,
        tmp_path / "r.sqlite",
        session_check=lambda: (True, "test:1", ""),
    )
    with pytest.raises(RuntimeError):
        await c.dispatch({"method": "observe"})
    c.epoch = "epoch-123"
    c.state.change(sharing=True, armed=True)
    p = permit()
    p.expires_at = time.time() - 1
    p.sign("secret")
    rejected = await c.dispatch({"method": "execute", "arguments": p.model_dump()})
    assert not rejected["ok"] and rejected["dispatched"] is False
    assert not rejected["outcome_unknown"] and c.state.armed
    await c.local_stop()
    assert not c.state.armed and c.state.sharing
    c.journal.close()


def test_dead_connection_revokes_control():
    state = LocalState()
    state.change(sharing=True, armed=True)
    state.last_contact -= 16
    with pytest.raises(RuntimeError):
        state.check(write=True)
    assert not state.armed


async def test_stop_terminates_hung_owned_worker(tmp_path):
    worker = Worker(tmp_path, "desktop")
    worker.process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-c",
        "import sys,time;sys.stdin.readline();time.sleep(120)",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
    )
    owned = worker.process
    operation = asyncio.create_task(worker.call("observe"))
    await asyncio.sleep(0.05)
    started = time.monotonic()
    await asyncio.wait_for(worker.stop(), 2)
    with pytest.raises(RuntimeError):
        await operation
    assert time.monotonic() - started < 2 and owned.returncode is not None
