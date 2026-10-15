import io
import json
import sys
import time
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from agentbot_windows.native import NativeDesktop


class ElementUnavailable(Exception):
    def __init__(self, hresult=-2147220991):
        self.hresult = hresult
        super().__init__("An event was unable to invoke any of the subscribers")


@pytest.fixture
def native(monkeypatch):
    monkeypatch.setattr("agentbot_windows.win_session.session_check", lambda: (True, "test", ""))
    monkeypatch.setattr("agentbot_windows.native.time.sleep", Mock())
    desktop = NativeDesktop.__new__(NativeDesktop)
    desktop.scope = "window"
    desktop.window_handle, desktop.window_pid, desktop.window_created = 10, 100, 1.0
    old = SimpleNamespace(handle=10, pid=100, created=1.0, set_focus=Mock())
    new = SimpleNamespace(handle=10, pid=100, created=1.0, set_focus=Mock())
    desktop.window = old
    desktop.observations = {"old-observation": {"time": time.time(), "windows": old}}
    desktop.win32gui = SimpleNamespace(IsWindow=Mock(return_value=True), GetForegroundWindow=Mock(return_value=10))
    desktop.inspector = SimpleNamespace(
        get_desktop_windows=Mock(side_effect=AssertionError("Do not inspect unrelated windows")),
        find_control_elements_in_descendants=Mock(return_value=[]),
    )
    desktop.info = lambda window: {
        "handle": window.handle, "pid": window.pid, "created": window.created,
        "process": "fixture.exe", "name": "Fixture", "rect": [0, 0, 100, 100], "dpi": 96,
    }
    desktop.capture = Mock(return_value={"fixture_capture": True})
    desktop.execute = Mock(side_effect=AssertionError("Never replay input"))
    acquire = Mock(return_value=new)
    monkeypatch.setitem(sys.modules, "pywinauto.uia_element_info", SimpleNamespace(UIAElementInfo=acquire))
    monkeypatch.setitem(sys.modules, "pywinauto.controls.uiawrapper", SimpleNamespace(UIAWrapper=lambda element: element))
    return SimpleNamespace(desktop=desktop, old=old, new=new, acquire=acquire)


@pytest.mark.parametrize("hresult", [-2147220991, 0x80040201])
def test_observation_recovers_stale_elements_with_a_new_scoped_root(native, hresult):
    desktop = native.desktop
    desktop.inspector.find_control_elements_in_descendants.side_effect = [ElementUnavailable(hresult), []]
    result = desktop.read("observe")
    assert result["window_id"] == "10" and result["scope"] == "window"
    assert list(desktop.observations) == [result["observation_id"]]
    assert desktop.window is native.new
    native.acquire.assert_called_once_with(handle_or_elem=10)
    desktop.inspector.get_desktop_windows.assert_not_called()
    desktop.execute.assert_not_called()
    native.old.set_focus.assert_not_called()
    native.new.set_focus.assert_not_called()


def test_capture_failure_discards_the_partially_built_observation(native):
    desktop = native.desktop
    desktop.capture.side_effect = [ElementUnavailable(), {"fixture_capture": True}]
    result = desktop.read("observe")
    assert list(desktop.observations) == [result["observation_id"]]
    assert desktop.capture.call_count == 2
    assert desktop.window is native.new
    desktop.execute.assert_not_called()


@pytest.mark.parametrize("operation", ["observe", "capture"])
def test_permanent_element_loss_stops_after_three_read_attempts(native, operation):
    desktop = native.desktop
    failing_read = Mock(side_effect=ElementUnavailable())
    setattr(desktop, operation, failing_read)
    with pytest.raises(RuntimeError, match="three attempts.*0x80040201.*not replayed"):
        desktop.read(operation)
    assert failing_read.call_count == 3
    assert not desktop.observations and desktop.window is None
    assert (desktop.scope, desktop.window_handle, desktop.window_pid, desktop.window_created) == ("window", 10, 100, 1.0)
    desktop.execute.assert_not_called()


def test_reacquired_window_must_still_match_the_paired_process(native):
    desktop = native.desktop
    native.new.created = 2.0
    desktop.inspector.find_control_elements_in_descendants.side_effect = ElementUnavailable()
    with pytest.raises(RuntimeError, match="Shared application was replaced"):
        desktop.read("observe")
    assert desktop.inspector.find_control_elements_in_descendants.call_count == 1
    desktop.inspector.get_desktop_windows.assert_not_called()
    desktop.execute.assert_not_called()


def test_locked_session_stops_read_retries(native, monkeypatch):
    desktop = native.desktop
    desktop.observe = Mock(side_effect=ElementUnavailable())
    monkeypatch.setattr("agentbot_windows.win_session.session_check", Mock(side_effect=[(True, "test", ""), (False, "test", "Locked")]))
    with pytest.raises(RuntimeError, match="interactive desktop is unavailable"):
        desktop.read("observe")
    desktop.observe.assert_called_once()


def test_other_com_errors_are_not_retried(native):
    desktop = native.desktop
    error = ElementUnavailable(0x80070005)
    desktop.observe = Mock(side_effect=error)
    with pytest.raises(ElementUnavailable) as caught:
        desktop.read("observe")
    assert caught.value is error
    desktop.observe.assert_called_once()


def test_read_entrypoint_cannot_execute_or_retry_input(native):
    with pytest.raises(ValueError, match="Only observation and capture"):
        native.desktop.read("execute")
    native.desktop.execute.assert_not_called()


def test_worker_routes_reads_through_recovery_without_restarting(native, monkeypatch, tmp_path):
    from agentbot_windows import worker

    constructor = Mock(return_value=native.desktop)
    monkeypatch.setattr("agentbot_windows.native.NativeDesktop", constructor)
    monkeypatch.setattr(worker, "qualify_source", lambda path: path)
    monkeypatch.setattr(worker.logging, "disable", lambda _: None)
    monkeypatch.setattr(sys, "path", list(sys.path))
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["worker", "--source", str(tmp_path), "--kind", "desktop"])
    native.desktop.inspector.find_control_elements_in_descendants.side_effect = [ElementUnavailable(), []]
    monkeypatch.setattr(sys, "stdin", io.StringIO('\n'.join(json.dumps({"method": op}) for op in ["observe", "capture"]) + '\n'))
    output = io.StringIO()
    monkeypatch.setattr(sys, "stdout", output)
    worker.main()
    responses = [json.loads(line) for line in output.getvalue().splitlines()]
    assert len(responses) == 2 and all("result" in item for item in responses)
    assert responses[0]["result"]["window_id"] == "10"
    constructor.assert_called_once()
    native.desktop.execute.assert_not_called()
