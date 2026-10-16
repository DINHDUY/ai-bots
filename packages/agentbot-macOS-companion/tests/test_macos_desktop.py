"""Explicit interactive qualification; skips fail the required native gate."""

import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

pytestmark = pytest.mark.macos_desktop
ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture
def desktop():
    if sys.platform != "darwin" or os.environ.get("AGENTBOT_MACOS_DESKTOP_TEST") != "1":
        pytest.skip("Requires explicitly enabled interactive macOS session")
    from agentbot_macos.session import permissions

    health = permissions()
    if not health["ready"]:
        pytest.skip(health["reason"])
    import AppKit
    from agentbot_macos.capture import windows
    from agentbot_macos.native import NativeRuntime
    from agentbot_macos.oi_bridge import OpenInterface

    previous = AppKit.NSWorkspace.sharedWorkspace().frontmostApplication()
    process = subprocess.Popen(
        [sys.executable, str(Path(__file__).with_name("owned_app.py"))],
        stdout=subprocess.PIPE,
        text=True,
    )
    try:
        runtime = NativeRuntime(
            OpenInterface(
                ROOT / "data/oi/source", ROOT / "packages/agentbot-macOS-companion/upstream.json"
            )
        )
        deadline = time.monotonic() + 10
        target = None
        while time.monotonic() < deadline:
            target = next((w for w in windows() if w["pid"] == process.pid), None)
            if target:
                break
            time.sleep(0.05)
        assert target, "Owned fixture window did not appear"
        yield runtime, target
    finally:
        process.terminate()
        process.wait(timeout=5)
        if previous:
            previous.activateWithOptions_(AppKit.NSApplicationActivateIgnoringOtherApps)


def perform(runtime, target, function, arguments, control=""):
    from agentbot_macos.actions import MacAction

    observed = runtime.observe("window", target["id"], 1)
    action = MacAction(
        function=function,
        observation_id=observed["observation_id"],
        window_id=target["id"],
        control_id=control,
        arguments=arguments,
    )
    return runtime.execute(action, "window", target["id"], 1, time.time() + 8)


def test_owned_window_capture_ax_ocr_and_literal_unicode(desktop):
    runtime, target = desktop
    observed = runtime.observe("window", target["id"], 1)
    assert observed["capture"]["width"] >= target["bounds"][2]
    assert observed["capture"]["scale_x"] >= 1
    editor = next(c for c in observed["controls"] if c["editable"] and c["focused"])
    assert editor["value"] == "Agent Control fixture"
    assert any(e["source"] == "ocr" for e in runtime.detect()["elements"])
    assert perform(runtime, target, "set_text", {"text": "Xin chào 日本語 👩🏽‍💻"}, editor["id"])[
        "effect_observed"
    ]
    assert perform(runtime, target, "key_input", {"keys": ["command", "a"]})["ok"]
    result = perform(
        runtime, target, "type_text", {"text": "Tiếng Việt café 日本語 🧪"}, editor["id"]
    )
    assert result["dispatched"] and not result["effect_observed"]
    time.sleep(0.2)
    after = runtime.observe("window", target["id"], 1)
    assert any(c.get("value") == "Tiếng Việt café 日本語 🧪" for c in after["controls"])


def test_owned_window_mouse_and_stale_observation(desktop):
    from agentbot_macos.actions import MacAction

    runtime, target = desktop
    for function, args in [
        ("focus_window", {}),
        ("move", {"x": 0.5, "y": 0.5}),
        ("click", {"x": 0.5, "y": 0.5}),
        ("drag", {"x": 0.3, "y": 0.3, "to_x": 0.6, "to_y": 0.3, "duration": 0.2}),
        ("scroll", {"amount": 1}),
        ("wait", {"seconds": 0.1}),
    ]:
        assert perform(runtime, target, function, args)["ok"], function
    observation = runtime.observe("window", target["id"], 1)
    action = MacAction(
        function="click",
        observation_id=observation["observation_id"],
        window_id=target["id"],
        arguments={"x": 0.5, "y": 0.5},
    )
    runtime.observation["created_at"] -= 31
    result = runtime.execute(action, "window", target["id"], 1, time.time() + 8)
    assert not result["dispatched"] and result["code"] == "stale_target"
