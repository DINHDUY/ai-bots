"""Explicit interactive qualification; touches only this script's fixture window."""

import asyncio
import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

_TEST_DIRECTORY = str(Path(__file__).resolve().parent)
if _TEST_DIRECTORY not in sys.path:
    sys.path.insert(0, _TEST_DIRECTORY)

from native_support import fixture, qualify_planner, qualify_text


async def worker_probe(source, hwnd):
    from agentbot_windows.protocol import Permit, WindowsAction
    from agentbot_windows.service import Companion
    from agentbot_windows.win_session import session_check

    with tempfile.TemporaryDirectory(prefix="agent-control-ufo-") as directory:
        c = Companion(
            {"token": "fixture-key", "name": "Fixture"},
            source,
            Path(directory) / "receipts.sqlite",
            session_check=session_check,
        )
        c.desktop.window = hwnd
        c.state.change(sharing=True, armed=True)
        try:
            observation = await c.dispatch({"method": "observe"})
            await c.dispatch(
                {
                    "method": "planner",
                    "arguments": {
                        "operation": "start",
                        "request": "Type into the fixture",
                    },
                }
            )
            prompt = await c.dispatch(
                {
                    "method": "planner",
                    "arguments": {"operation": "prompt", "observation": observation},
                }
            )
            assert prompt["role"] == "HostAgent" and prompt["messages"]
            c.state.last_contact = time.monotonic()
            control = next(v for v in observation["controls"] if v["type"] == "Edit")
            action = WindowsAction(
                function="set_edit_text",
                observation_id=observation["observation_id"],
                window_id=str(hwnd),
                control_id=control["id"],
                arguments={"text": "Verified through companion IPC"},
            )
            permit = Permit(
                action_id="fixture-action-ipc",
                session_id="fixture-session",
                generation=1,
                epoch=c.epoch,
                local_revision=c.state.revision,
                expires_at=time.time() + 8,
                action=action,
            ).sign("fixture-key")
            result = await c.dispatch({"method": "execute", "arguments": permit.model_dump()})
            assert result["effect_observed"], result
            assert (
                await c.dispatch({"method": "execute", "arguments": permit.model_dump()}) == result
            )
        finally:
            await c.local_stop()
            c.journal.close()


def qualify():
    import win32con
    import win32gui

    root = Path(__file__).resolve().parents[3]
    sys.path.insert(0, str(root / "packages/agentbot-windows-companion/src"))
    from agentbot_windows.bootstrap import qualify_source
    from agentbot_windows.win_session import desktop_lock, session_check, watch_input

    source = qualify_source(root / "data/ufo/upstream")
    assert session_check()[0], "An unlocked interactive Windows session is required"
    release = desktop_lock()
    try:
        try:
            desktop_lock()
        except RuntimeError as exc:
            assert "already running" in str(exc)
        else:
            raise AssertionError("Second companion could reserve the same desktop")
    finally:
        release()
    takeovers = []
    writing = [False]
    watcher = watch_input(takeovers.append, lambda: writing[0])
    assert watcher.wait(3), "Independent input hooks/hotkey unavailable"
    child = subprocess.Popen(
        [sys.executable, str(Path(__file__).resolve()), "--fixture"],
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
            focus = win32gui.GetForegroundWindow()
            observation = desktop.observe()
            assert win32gui.GetForegroundWindow() == focus, "Observe changed focus"
            assert len(observation["windows"]) == 1 and observation["window_id"] == str(hwnd)
            assert observation["capture"]["width"] < 600 and observation["capture"]["height"] < 300
            planner = UfoPlanner("Type test text")
            assert planner.prompt(observation)["role"] == "HostAgent"
            proposal = planner.response(
                json.dumps(
                    {
                        "observation": "fixture",
                        "thought": "select",
                        "function": "select_application_window",
                        "arguments": {
                            "id": str(hwnd),
                            "name": observation["windows"][0]["name"],
                        },
                        "current_subtask": "Type",
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
            text = "UFO literal {ENTER} ^s \u2713"
            action = {
                "function": "set_edit_text",
                "arguments": {"text": text},
                "target": {"kind": "control", "id": edit["id"], "name": edit["name"]},
                "status": "CONTINUE",
            }
            proposal = planner.response(
                json.dumps({"observation": "edit", "thought": "type", "action": action})
            )
            result = desktop.execute(proposal["action"], expires_at=time.time() + 8)
            assert result["effect_observed"], result
            observation = desktop.observe()
            button = next(c for c in observation["controls"] if c["name"] == "Test click")
            click = {
                "function": "click_input",
                "observation_id": observation["observation_id"],
                "window_id": str(hwnd),
                "control_id": button["id"],
                "arguments": {},
            }
            writing[0] = True
            assert desktop.execute(click, expires_at=time.time() + 8)["ok"]
            time.sleep(0.1)
            writing[0] = False
            assert not takeovers, takeovers
            assert win32gui.GetWindowText(win32gui.GetDlgItem(hwnd, 102)) == "Clicked"
            win32gui.MoveWindow(hwnd, 150, 150, 520, 260, True)
            try:
                desktop.execute(click, expires_at=time.time() + 8)
            except RuntimeError as exc:
                assert "stale_target" in str(exc)
            else:
                raise AssertionError("Moved target accepted")
        asyncio.run(worker_probe(source, hwnd))
        print(
            "PASS: input watcher; scoped capture without focus; UFO Host/App prompts; focus; literal Unicode text; click; stale target rejection; companion worker IPC and receipt replay"
        )
    finally:
        if win32gui.IsWindow(hwnd):
            win32gui.PostMessage(hwnd, win32con.WM_CLOSE, 0, 0)
        try:
            child.wait(timeout=5)
        except subprocess.TimeoutExpired:
            child.kill()
            child.wait()


if __name__ == "__main__":
    if "--fixture" in sys.argv:
        fixture()
    elif "--text-only" in sys.argv:
        qualify_text()
    elif "--planner-only" in sys.argv:
        qualify_planner()
    else:
        qualify()
