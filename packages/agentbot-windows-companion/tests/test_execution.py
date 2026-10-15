import io
import json
import sys
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from agentbot_windows.execution import ActionNotDispatched
from agentbot_windows.native import NativeDesktop
from agentbot_windows.protocol import Permit, WindowsAction, digest
from agentbot_windows.service import Companion, Worker, WorkerStopped


@pytest.fixture
def desktop(monkeypatch):
    executor = Mock(return_value=None)
    for module, attributes in {
        "ufo.automator.puppeteer": {"AppPuppeteer": Mock()},
        "ufo.automator.action_execution": {"ActionExecutor": lambda: SimpleNamespace(execute=executor)},
        "ufo.agents.processors.schemas.actions": {"ActionCommandInfo": SimpleNamespace},
        "ufo.agents.processors.schemas.target": {"TargetInfo": SimpleNamespace},
    }.items():
        monkeypatch.setitem(sys.modules, module, SimpleNamespace(**attributes))
    monkeypatch.setattr("agentbot_windows.win_session.session_check", lambda: (True, "test", ""))
    native = NativeDesktop.__new__(NativeDesktop)
    native.scope = "window"
    native.window = Mock(handle=10)
    info = {"handle": 10, "process": "test.exe", "name": "Test", "rect": [0, 0, 100, 100]}
    native.info = Mock(return_value=info)
    native.win32gui = SimpleNamespace(GetForegroundWindow=Mock(return_value=10))
    control = SimpleNamespace(
        element_info=SimpleNamespace(
            _element=SimpleNamespace(CurrentIsPassword=False, CurrentHasKeyboardFocus=True),
            control_type="Edit", automation_id="editor",
        ),
        rectangle=lambda: SimpleNamespace(left=0, top=0, right=100, bottom=20),
        window_text=lambda: "Editor", is_enabled=lambda: True, is_visible=lambda: True,
        iface_value=SimpleNamespace(CurrentIsReadOnly=False, CurrentValue=""),
        set_edit_text=Mock(),
        set_focus=Mock(),
    )
    metadata = {
        "id": "2", "name": "Editor", "type": "Edit", "kind": "control",
        "automation_id": "editor", "rect": [0, 0, 100, 20], "writable_text": True,
        "text_input_method": "set_edit_text",
    }
    observed = {
        "time": time.time(), "windows": {"10": (native.window, info)},
        "controls": {"2": (control, digest(metadata))}, "selected": "10",
    }
    native.observations = {"observation-test": observed}
    native.fresh = lambda item: item
    action = {
        "function": "set_edit_text", "observation_id": "observation-test",
        "window_id": "10", "control_id": "2", "arguments": {"text": "Literal {ENTER} ^s ✓"},
    }
    return SimpleNamespace(native=native, control=control, metadata=metadata,
                           observed=observed, action=action, executor=executor)


@pytest.mark.parametrize("failure", ["expired", "old_observation", "focus", "geometry", "readonly", "read_error"])
def test_rejections_before_input_do_not_claim_an_unknown_outcome(desktop, failure):
    expires = time.time() + 8
    if failure == "expired": expires -= 10
    if failure == "old_observation": desktop.observed["time"] -= 31
    if failure == "focus": desktop.native.win32gui.GetForegroundWindow.return_value = 99
    if failure == "geometry": desktop.native.info.return_value = {"rect": [1, 2, 3, 4]}
    if failure == "readonly":
        desktop.control.iface_value.CurrentIsReadOnly = True
        desktop.metadata["writable_text"] = False
        desktop.metadata["text_input_method"] = None
        desktop.observed["controls"]["2"] = (desktop.control, digest(desktop.metadata))
    if failure == "read_error": desktop.native.info.side_effect = RuntimeError("UIA read failed")
    with pytest.raises(ActionNotDispatched) as error:
        desktop.native.execute(desktop.action, expires_at=expires)
    assert error.value.result()["dispatched"] is False
    assert error.value.result()["outcome_unknown"] is False
    if failure in {"old_observation", "focus", "geometry"}:
        assert error.value.code == "stale_target"
    if failure == "readonly": assert error.value.code == "unsupported_text_control"
    desktop.executor.assert_not_called()
    desktop.native.window.set_focus.assert_not_called()


def test_text_is_verified_after_executor_dispatch(desktop):
    def write(command, *_):
        desktop.control.iface_value.CurrentValue = command.arguments["text"]
    desktop.executor.side_effect = write
    result = desktop.native.execute(desktop.action, expires_at=time.time() + 8)
    assert result["ok"] and result["effect_observed"]
    desktop.executor.assert_called_once()


def test_exception_after_input_is_never_reported_as_not_dispatched(desktop):
    def write_then_fail(*_):
        desktop.control.iface_value.CurrentValue = "May have been written"
        raise RuntimeError("UIA lost result after write")
    desktop.executor.side_effect = write_then_fail
    with pytest.raises(RuntimeError, match="UIA lost result") as error:
        desktop.native.execute(desktop.action, expires_at=time.time() + 8)
    assert not isinstance(error.value, ActionNotDispatched)


def test_rich_text_editor_requires_a_fresh_typing_proposal(desktop):
    desktop.control.element_info.class_name = "ck ck-editor__editable"
    desktop.metadata["text_input_method"] = "type_text"
    desktop.observed["controls"]["2"] = (desktop.control, digest(desktop.metadata))
    with pytest.raises(ActionNotDispatched) as error:
        desktop.native.execute(desktop.action, expires_at=time.time() + 8)
    assert error.value.code == "text_method_changed"
    desktop.executor.assert_not_called()


def test_uia_element_loss_during_input_is_not_retried(desktop):
    class ElementUnavailable(Exception):
        hresult = -2147220991

    desktop.executor.side_effect = ElementUnavailable("Element disappeared during input")
    with pytest.raises(ElementUnavailable):
        desktop.native.execute(desktop.action, expires_at=time.time() + 8)
    desktop.executor.assert_called_once()


def test_unfocused_editor_rejects_typing_before_executor_or_focus_change(desktop):
    desktop.action["function"] = "type_text"
    desktop.control.element_info._element.CurrentHasKeyboardFocus = False
    with pytest.raises(ActionNotDispatched) as error:
        desktop.native.execute(desktop.action, expires_at=time.time() + 8)
    assert error.value.code == "editor_not_focused"
    assert error.value.result()["dispatched"] is False
    assert error.value.result()["outcome_unknown"] is False
    desktop.executor.assert_not_called()
    desktop.control.set_focus.assert_not_called()


def test_typing_preserves_the_already_focused_editor(desktop, monkeypatch):
    desktop.action["function"] = "type_text"
    original_focus = desktop.control.set_focus
    monkeypatch.setattr("agentbot_windows.text_input.register_type_text", lambda _: None)
    # This is the focus call made by UFO's receiver constructor.
    desktop.executor.side_effect = lambda _command, _puppet, controls, _window: controls["2"].set_focus()
    result = desktop.native.execute(desktop.action, expires_at=time.time() + 8)
    assert result["ok"] and not result["effect_observed"]
    original_focus.assert_not_called()


def test_typing_rechecks_editor_focus_and_keeps_post_dispatch_expiry_uncertain(desktop, monkeypatch):
    desktop.action["function"] = "type_text"
    checks = []
    monkeypatch.setattr("agentbot_windows.text_input.register_type_text", checks.append)
    def lose_focus(*args):
        desktop.control.element_info._element.CurrentHasKeyboardFocus = False
        checks[0]()
    desktop.executor.side_effect = lose_focus
    with pytest.raises(RuntimeError, match="editor lost keyboard focus") as error:
        desktop.native.execute(desktop.action, expires_at=time.time() + 8)
    assert not isinstance(error.value, ActionNotDispatched)
    desktop.control.element_info._element.CurrentHasKeyboardFocus = True
    desktop.executor.side_effect = ActionNotDispatched("expired after first batch", "permit_expired")
    with pytest.raises(RuntimeError, match="expired after first batch") as error:
        desktop.native.execute(desktop.action, expires_at=time.time() + 8)
    assert not isinstance(error.value, ActionNotDispatched)


def test_worker_returns_structured_rejection_and_keeps_serving(desktop, monkeypatch, tmp_path):
    from agentbot_windows import worker
    monkeypatch.setattr(worker, "qualify_source", lambda path: path)
    monkeypatch.setattr(worker.logging, "disable", lambda level: None)
    monkeypatch.setattr(sys, "path", list(sys.path))
    monkeypatch.setattr("agentbot_windows.native.NativeDesktop", lambda *args: desktop.native)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["worker", "--source", str(tmp_path), "--kind", "desktop"])
    command = {"method": "execute", "arguments": desktop.action, "expires_at": time.time() - 1}
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(command) + "\n" + json.dumps(command) + "\n"))
    output = io.StringIO()
    monkeypatch.setattr(sys, "stdout", output)
    worker.main()
    answers = [json.loads(line) for line in output.getvalue().splitlines()]
    assert len(answers) == 2
    assert all(answer["result"]["code"] == "permit_expired" for answer in answers)
    desktop.executor.assert_not_called()


@pytest.mark.parametrize("failure", ["stale", "editor_focus", "stopped_before", "stopped_after", "worker_error"])
async def test_companion_persists_known_rejection_or_uncertainty_without_replay(tmp_path, failure):
    companion = Companion(
        {"name": "Test", "token": "secret"}, tmp_path, tmp_path / "receipts.sqlite",
        session_check=lambda: (True, "test:1", ""),
    )
    companion.state.change(sharing=True, armed=True)
    permit = Permit(
        action_id="action-test", session_id="session-test", generation=1,
        epoch=companion.epoch, local_revision=companion.state.revision,
        expires_at=time.time() + 8,
        action=WindowsAction(function="type_text" if failure == "editor_focus" else "set_edit_text", observation_id="observe-test", window_id="10", control_id="2", arguments={"text": "Hello"}),
    ).sign("secret")
    errors = {
        "stale": ActionNotDispatched("stale_target: foreground changed", "stale_target"),
        "editor_focus": ActionNotDispatched("Click the editor first; no text was sent", "editor_not_focused"),
        "stopped_before": WorkerStopped("Stopped locally"),
        "stopped_after": WorkerStopped("Stopped locally", dispatched=True),
        "worker_error": RuntimeError("Literal text input failed"),
    }
    companion.desktop.call = AsyncMock(side_effect=errors[failure])
    try:
        result = await companion.dispatch({"method": "execute", "arguments": permit.model_dump()})
        unknown = failure in {"stopped_after", "worker_error"}
        assert result["outcome_unknown"] is unknown
        assert companion.state.armed is not unknown
        assert str(errors[failure]) in result["text"]
        assert companion.journal.claim(permit) == result
        if not unknown:
            assert result["dispatched"] is False
            assert await companion.dispatch({"method": "execute", "arguments": permit.model_dump()}) == result
        companion.desktop.call.assert_awaited_once()
    finally:
        companion.journal.close()


async def test_worker_rejection_does_not_destroy_observations(tmp_path, monkeypatch):
    worker = Worker(tmp_path, "desktop")
    response = {"result": ActionNotDispatched("stale_target: moved", "stale_target").result()}
    process = SimpleNamespace(
        pid=123, returncode=None, stdin=SimpleNamespace(write=Mock(), drain=AsyncMock()),
        stdout=SimpleNamespace(readline=AsyncMock(return_value=(json.dumps(response) + "\n").encode())),
        kill=Mock(), wait=AsyncMock(),
    )
    worker.process = process
    monkeypatch.setattr("agentbot_windows.win_session.worker_job", lambda pid: SimpleNamespace(Close=Mock()))
    try:
        result = await worker.call("execute")
        assert result["code"] == "stale_target"
        assert worker.process is process
        process.kill.assert_not_called()
    finally:
        await worker.stop()
