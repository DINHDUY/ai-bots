"""Portable native-boundary tests; OS calls are replaced and emit no real input."""

import copy
import json
import time

import pytest
from agentbot_macos import native, text_input
from agentbot_macos.actions import MacAction
from agentbot_macos.planner import Planner
from agentbot_macos.results import NotDispatched


class OI:
    def __init__(self):
        self.calls = []

    def execute(self, function, arguments):
        self.calls.append((function, arguments))


@pytest.fixture
def runtime(monkeypatch):
    window = {
        "id": "1",
        "pid": 123,
        "created": 1.0,
        "bundle_id": "owned.test",
        "bounds": [100.0, 100.0, 400.0, 200.0],
        "name": "Owned",
        "foreground": True,
    }
    monkeypatch.setattr(native, "windows", lambda: [copy.deepcopy(window)])
    monkeypatch.setattr(native, "require_session", lambda *a: {"console_session": "user:1"})
    monkeypatch.setattr(text_input, "require_released_modifiers", lambda: None)
    value = native.NativeRuntime(OI())
    value.observation = {
        "observation_id": "observation-1",
        "created_at": time.time(),
        "console_session": "user:1",
        "scope": "window",
        "selected": "1",
        "revision": 1,
        "window": copy.deepcopy(window),
        "controls": [],
    }
    return value, window


def execute(runtime, function, args):
    action = MacAction(
        function=function, observation_id="observation-1", window_id="1", arguments=args
    )
    return runtime.execute(action, "window", "1", 1, time.time() + 8)


def test_scrolling_cannot_target_pointer_outside_admitted_window(runtime):
    value, _ = runtime
    assert execute(value, "scroll", {"amount": 2})["ok"]
    assert value.oi.calls == [("scroll", {"clicks": 2, "x": 300.0, "y": 200.0})]


@pytest.mark.parametrize("change", ["geometry", "pid", "focus", "title", "observation"])
def test_changed_targets_do_not_dispatch(runtime, change):
    value, window = runtime
    if change == "geometry":
        window["bounds"][0] += 5
    elif change == "pid":
        window["pid"] += 1
    elif change == "focus":
        window["foreground"] = False
    elif change == "title":
        window["name"] = "Other document"
    else:
        value.observation["created_at"] -= 31
    result = execute(value, "click", {"x": 0.5, "y": 0.5})
    assert not result["dispatched"] and result["code"] == "stale_target"
    assert not value.oi.calls


def test_physical_modifiers_rejected_before_input(runtime, monkeypatch):
    def held():
        raise NotDispatched("Physical modifier held", "physical_modifier")

    monkeypatch.setattr(text_input, "require_released_modifiers", held)
    value, _ = runtime
    result = execute(value, "key_input", {"keys": ["enter"]})
    assert not result["dispatched"] and not result["outcome_unknown"]
    assert not value.oi.calls


def test_failure_after_native_call_is_unknown(runtime):
    value, _ = runtime

    def failed(*_):
        raise RuntimeError("Native callback lost")

    value.oi.execute = failed
    result = execute(value, "click", {"x": 0.5, "y": 0.5})
    assert result["outcome_unknown"] and not result["ok"]


def test_planner_requires_current_observed_postcondition():
    planner = Planner("Pinned OI context")
    planner.start("Write hello")
    planner.prompt(
        {
            "observation_id": "observation-1",
            "window": {"name": "Owned"},
            "controls": [{"id": "1", "value": "hello"}],
            "capture": {"image": "fixture"},
        }
    )
    planner.result({"ok": True})
    response = {
        "finished": True,
        "text": "Done",
        "evidence": {"observation_id": "stale-id", "control_id": "1", "value": "hello"},
    }
    assert not planner.response(json.dumps(response))["effect_observed"]
    response["evidence"]["observation_id"] = "observation-1"
    assert planner.response(json.dumps(response))["effect_observed"]
    with pytest.raises(ValueError):
        planner.response(
            json.dumps({"action": {"function": "exec", "arguments": {"code": "anything"}}})
        )


def test_display_inspects_each_window_once_under_one_deadline(runtime, monkeypatch):
    value, window = runtime
    other = {**window, "id": "2", "foreground": False}
    monkeypatch.setattr(native, "windows", lambda: [window, other])
    calls = []

    def inspect(target, **kwargs):
        calls.append((target["id"], kwargs))
        return ([{"id": "owned"}], {"owned": "handle"}) if kwargs["include_controls"] else ([], {})

    monkeypatch.setattr(native.ax, "inspect", inspect)
    monkeypatch.setattr(native, "screenshot", lambda *a: {"image": "fixture"})
    observed = value.observe("display", "1", 2)
    assert [target for target, _ in calls] == ["1", "2"]
    assert [options["include_controls"] for _, options in calls] == [True, False]
    assert calls[0][1]["deadline"] == calls[1][1]["deadline"]
    assert observed["controls"] == [{"id": "owned"}]
    assert value.handles == {"owned": "handle"}


def test_failed_display_scan_cannot_capture_or_retain_previous_observation(runtime, monkeypatch):
    value, window = runtime
    other = {**window, "id": "2", "foreground": False}
    monkeypatch.setattr(native, "windows", lambda: [window, other])
    value.handles = {"previous": object()}

    def inspect(target, **kwargs):
        if target["id"] == "2":
            raise NotDispatched("Secure input", "secure_surface")
        return [{"id": "owned"}], {"owned": "handle"}

    def unexpected(*args):
        pytest.fail("Incomplete AX inspection must not capture")

    monkeypatch.setattr(native.ax, "inspect", inspect)
    monkeypatch.setattr(native, "screenshot", unexpected)
    with pytest.raises(NotDispatched, match="Secure input"):
        value.observe("display", "1", 2)
    assert value.observation is None and value.handles == {}
