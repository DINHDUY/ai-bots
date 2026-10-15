import contextlib
import io
import json
import os
import subprocess
import sys
import time
from pathlib import Path


def fixture():
    import win32api
    import win32con as c
    import win32gui as g

    def procedure(hwnd, message, wparam, lparam):
        if message == c.WM_DESTROY:
            g.PostQuitMessage(0)
            return 0
        if message == c.WM_COMMAND and wparam & 0xFFFF == 101:
            g.SetWindowText(g.GetDlgItem(hwnd, 102), "Clicked")
            return 0
        return g.DefWindowProc(hwnd, message, wparam, lparam)

    wc = g.WNDCLASS()
    wc.lpszClassName = "AgentControlUFOQualification"
    wc.lpfnWndProc = procedure
    wc.hInstance = win32api.GetModuleHandle(None)
    wc.hbrBackground = c.COLOR_WINDOW + 1
    g.RegisterClass(wc)
    hwnd = g.CreateWindow(
        wc.lpszClassName,
        "Agent Control UFO test fixture",
        c.WS_OVERLAPPEDWINDOW,
        120,
        120,
        520,
        260,
        0,
        0,
        wc.hInstance,
        None,
    )
    g.CreateWindowEx(
        c.WS_EX_CLIENTEDGE,
        "EDIT",
        "",
        c.WS_CHILD | c.WS_VISIBLE | c.ES_AUTOHSCROLL,
        20,
        25,
        450,
        35,
        hwnd,
        100,
        wc.hInstance,
        None,
    )
    g.CreateWindow(
        "BUTTON",
        "Test click",
        c.WS_CHILD | c.WS_VISIBLE,
        20,
        85,
        150,
        40,
        hwnd,
        101,
        wc.hInstance,
        None,
    )
    g.CreateWindow(
        "STATIC",
        "Waiting",
        c.WS_CHILD | c.WS_VISIBLE,
        200,
        90,
        200,
        40,
        hwnd,
        102,
        wc.hInstance,
        None,
    )
    g.ShowWindow(hwnd, c.SW_SHOW)
    g.UpdateWindow(hwnd)
    print(hwnd, flush=True)
    g.PumpMessages()


def qualify_planner():
    """Validate real UFO schemas with synthetic observations; no desktop input."""
    root = Path(__file__).resolve().parents[3]
    sys.path.insert(0, str(root / "packages/agentbot-windows-companion/src"))
    from agentbot_windows.bootstrap import qualify_source

    source = qualify_source(root / "data/ufo/upstream")
    sys.path.insert(0, str(source))
    os.chdir(source)
    with (
        contextlib.redirect_stdout(io.StringIO()),
        contextlib.redirect_stderr(io.StringIO()),
    ):
        from agentbot_windows.planner import UfoPlanner

        planner = UfoPlanner("Correct a draft in the synthetic editor")
        observation = {
            "observation_id": "observation-synthetic",
            "window_id": "10",
            "windows": [{"id": "10", "name": "Synthetic editor", "process": "notepad.exe"}],
            "controls": [
                {
                    "id": "2",
                    "name": "Editor",
                    "type": "Edit",
                    "writable_text": True,
                    "has_keyboard_focus": True,
                }
            ],
        }
        planner.prompt(observation)
        planner.response(
            json.dumps(
                {
                    "observation": "fixture",
                    "thought": "select",
                    "function": "select_application_window",
                    "arguments": {"id": "10", "name": "Synthetic editor"},
                    "current_subtask": "Correct a draft",
                    "status": "CONTINUE",
                }
            )
        )
        planner.result({"ok": True, "text": "Synthetic focus result"})
        assert planner.prompt(observation)["role"] == "AppAgent"
        previous = planner.last_action

        def response(keys):
            return json.dumps(
                {
                    "observation": "editor",
                    "thought": "correct draft",
                    "action": {
                        "function": "keyboard_input",
                        "arguments": {"keys": keys},
                        "target": {"kind": "control", "id": "2", "name": "Editor"},
                        "status": "CONTINUE",
                    },
                }
            )

        rejected = planner.response(response("^a{DELETE}"))
        assert rejected["proposal_rejected"] and "action" not in rejected
        assert planner.last_action is previous and len(planner.history) == 1
        assert rejected["text"] in planner.prompt(observation)["messages"][0]["content"]
        for index, keys in enumerate(["^a", "{DELETE}"]):
            planner.prompt({**observation, "observation_id": f"observation-corrected-{index}"})
            proposal = planner.response(response(keys))
            assert proposal["action"]["arguments"] == {"keys": keys}
            assert proposal["action"]["observation_id"] == f"observation-corrected-{index}"
            planner.result({"ok": True, "text": "Synthetic key result"})
        assert len(planner.history) == 3 and not planner.validation_feedback
    print(
        "PASS: real UFO proposal validation, preserved history, correction feedback, and separate Ctrl+A/Delete proposals; no desktop input or model call"
    )


def qualify_text():
    """Exercise Unicode typing without reserving a companion mutex or hotkey."""
    import win32con
    import win32gui

    root = Path(__file__).resolve().parents[3]
    sys.path.insert(0, str(root / "packages/agentbot-windows-companion/src"))
    from agentbot_windows.bootstrap import qualify_source
    from agentbot_windows.win_session import session_check

    source = qualify_source(root / "data/ufo/upstream")
    assert session_check()[0], "An unlocked interactive Windows session is required"
    original_focus = win32gui.GetForegroundWindow()
    child = subprocess.Popen(
        [sys.executable, str(Path(__file__).with_name("native_probe.py").resolve()), "--fixture"],
        stdout=subprocess.PIPE,
        text=True,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    hwnd = int(child.stdout.readline())
    try:
        sys.path.insert(0, str(source))
        os.chdir(source)
        with (
            contextlib.redirect_stdout(io.StringIO()),
            contextlib.redirect_stderr(io.StringIO()),
        ):
            from agentbot_windows.native import NativeDesktop
            from agentbot_windows.planner import UfoPlanner

            desktop = NativeDesktop("window", hwnd)
            planner = UfoPlanner("Type a literal draft in the fixture; do not send it")
            observation = desktop.observe()
            assert planner.prompt(observation)["role"] == "HostAgent"
            proposal = planner.response(
                json.dumps(
                    {
                        "observation": "fixture",
                        "thought": "select",
                        "function": "select_application_window",
                        "arguments": {"id": str(hwnd), "name": observation["windows"][0]["name"]},
                        "current_subtask": "Type a draft",
                        "status": "CONTINUE",
                    }
                )
            )
            result = desktop.execute(proposal["action"], expires_at=time.time() + 8)
            assert result["effect_observed"], result
            planner.result(result)
            observation = desktop.observe()
            assert planner.prompt(observation)["role"] == "AppAgent"
            edit = next(c for c in observation["controls"] if c["type"] == "Edit")
            assert edit["writable_text"]
            if not edit["has_keyboard_focus"]:
                from agentbot_windows.execution import ActionNotDispatched

                try:
                    desktop.execute(
                        {
                            "function": "type_text",
                            "arguments": {"text": "Not dispatched"},
                            "observation_id": observation["observation_id"],
                            "window_id": str(hwnd),
                            "control_id": edit["id"],
                        },
                        expires_at=time.time() + 8,
                    )
                except ActionNotDispatched as exc:
                    assert exc.code == "editor_not_focused"
                else:
                    raise AssertionError("Typing into an unfocused editor was accepted")
            proposal = planner.response(
                json.dumps(
                    {
                        "observation": "editor",
                        "thought": "focus the message editor first",
                        "action": {
                            "function": "click_input",
                            "arguments": {},
                            "target": {"kind": "control", "id": edit["id"], "name": edit["name"]},
                            "status": "CONTINUE",
                        },
                    }
                )
            )
            result = desktop.execute(proposal["action"], expires_at=time.time() + 8)
            assert result["ok"], result
            planner.result(result)
            observation = desktop.observe()
            assert planner.prompt(observation)["role"] == "AppAgent"
            edit = next(c for c in observation["controls"] if c["type"] == "Edit")
            assert edit["has_keyboard_focus"]
            literal = "Hello {ENTER} ^s +%() \u2713 \U0001f600"
            proposal = planner.response(
                json.dumps(
                    {
                        "observation": "editor",
                        "thought": "insert literal draft",
                        "action": {
                            "function": "type_text",
                            "arguments": {"text": literal},
                            "target": {"kind": "control", "id": edit["id"], "name": edit["name"]},
                            "status": "CONTINUE",
                        },
                    }
                )
            )
            result = desktop.execute(proposal["action"], expires_at=time.time() + 8)
            assert result["ok"] and not result["effect_observed"], result
            editor = desktop.fresh(
                desktop.observations[observation["observation_id"]]["controls"][edit["id"]][0]
            )
            deadline = time.monotonic() + 2
            while time.monotonic() < deadline:
                if editor.iface_value.CurrentValue == literal:
                    break
                time.sleep(0.05)
            assert editor.iface_value.CurrentValue == literal, repr(editor.iface_value.CurrentValue)
            assert win32gui.GetWindowText(win32gui.GetDlgItem(hwnd, 102)) == "Waiting"
            # Emulate the stale UIA element Teams can expose after a UI update.
            # Retry inspection only; the fixture's text and focus must not change.
            from comtypes import COMError

            inspect = desktop.inspector.find_control_elements_in_descendants
            attempts = []
            old_root = desktop.window

            def stale_once(*args, **kwargs):
                attempts.append(True)
                if len(attempts) == 1:
                    raise COMError(-2147220991, "Fixture element no longer available", None)
                return inspect(*args, **kwargs)

            desktop.inspector.find_control_elements_in_descendants = stale_once
            try:
                recovered = desktop.read("observe")
            finally:
                desktop.inspector.find_control_elements_in_descendants = inspect
            assert len(attempts) == 2 and desktop.window is not old_root
            assert list(desktop.observations) == [recovered["observation_id"]]
            assert recovered["window_id"] == str(hwnd)
            assert win32gui.GetForegroundWindow() == hwnd
            assert editor.iface_value.CurrentValue == literal
        print(
            "PASS: UFO Host/App proposal and executor; separate editor click and verified focus; literal Unicode typing; stale-read recovery with injected COM error; no input replay"
        )
    finally:
        if win32gui.IsWindow(hwnd):
            if win32gui.GetForegroundWindow() == hwnd and win32gui.IsWindow(original_focus):
                try:
                    win32gui.SetForegroundWindow(original_focus)
                except Exception:
                    pass
            win32gui.PostMessage(hwnd, win32con.WM_CLOSE, 0, 0)
        try:
            child.wait(timeout=5)
        except subprocess.TimeoutExpired:
            child.kill()
            child.wait()
