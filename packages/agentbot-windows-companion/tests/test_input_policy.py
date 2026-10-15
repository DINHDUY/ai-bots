import ctypes
import sys
from ctypes import wintypes
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from agentbot_windows.state import LocalState
from agentbot_windows.win_session import watch_input


def test_hand_off_is_local_and_does_not_grant_or_resume_control():
    state = LocalState()
    assert not state.hand_off
    state.set_hand_off(True)
    assert not state.sharing and not state.armed
    assert not state.should_pause_on_input(automating=True)
    with pytest.raises(RuntimeError):
        state.check(write=True)

    state.change(sharing=True, armed=True, reason="Ready")
    revision = state.check(write=True)
    assert not state.should_pause_on_input(automating=True)
    state.set_hand_off(False)
    assert state.should_pause_on_input(automating=True)
    assert not state.should_pause_on_input(automating=False)
    state.set_hand_off(True)
    assert state.check(write=True) == revision
    assert state.reason == "Ready"

    state.stop("Stopped locally")
    state.set_hand_off(False)
    state.set_hand_off(True)
    assert not state.armed
    assert state.reason == "Stopped locally"
    assert not LocalState().hand_off  # A new companion starts unchecked.


def test_hand_off_does_not_bypass_connection_loss():
    state = LocalState()
    state.change(sharing=True, armed=True)
    state.set_hand_off(True)
    state.last_contact -= 16
    with pytest.raises(RuntimeError, match="Backend connection lost"):
        state.check(write=True)
    assert not state.armed


@pytest.mark.parametrize("hand_off", [False, True])
def test_native_input_routes_obey_hand_off_but_emergency_stop_always_works(
    monkeypatch, hand_off
):
    # Exercise the real callbacks with fake Win32 APIs, without installing hooks
    # or sending any input to the user's desktop.
    state = LocalState()
    state.change(sharing=True, armed=True)
    state.set_hand_off(hand_off)
    stops, hooks, window_classes = [], {}, []
    user32 = Mock()
    user32.SetWindowsHookExW.side_effect = lambda kind, callback, *_: (
        hooks.setdefault(kind, callback) and kind
    )
    gui = SimpleNamespace(
        WNDCLASS=SimpleNamespace,
        RegisterClass=lambda cls: window_classes.append(cls) or 1,
        CreateWindowEx=lambda *args: 1,
        DefWindowProc=lambda *args: 0,
    )
    monkeypatch.setitem(sys.modules, "win32gui", gui)
    monkeypatch.setattr(ctypes, "WinDLL", lambda *args, **kwargs: user32, raising=False)
    monkeypatch.setattr(
        ctypes, "WINFUNCTYPE", lambda *args: lambda callback: callback, raising=False
    )
    monkeypatch.setattr(
        "agentbot_windows.win_session.mouse_activity_from_event", lambda *args: True
    )
    monkeypatch.setattr(
        "agentbot_windows.win_session.threading.Thread",
        lambda *, target, daemon: SimpleNamespace(start=target),
    )

    class Keyboard(ctypes.Structure):
        _fields_ = [
            ("vk", wintypes.DWORD), ("scan", wintypes.DWORD),
            ("flags", wintypes.DWORD), ("time", wintypes.DWORD),
            ("extra", ctypes.c_size_t),
        ]

    class Mouse(ctypes.Structure):
        _fields_ = [
            ("point", wintypes.POINT), ("data", wintypes.DWORD),
            ("flags", wintypes.DWORD), ("time", wintypes.DWORD),
            ("extra", ctypes.c_size_t),
        ]

    keyboard, mouse = Keyboard(), Mouse()

    def stop(reason):
        state.stop(reason)
        stops.append(reason)

    def first_message(message, *_):
        # Injected keyboard/buttons and SetCursorPos-style motion are not takeover.
        keyboard.flags, mouse.flags = 0x10, 1
        before = len(stops)
        hooks[13](0, 0x100, ctypes.addressof(keyboard))
        hooks[14](0, 0x201, ctypes.addressof(mouse))
        mouse.flags = 0
        hooks[14](0, 0x200, ctypes.addressof(mouse))
        assert state.armed and stops[before:] == []
        keyboard.flags = 0
        for emit, reason in [
            (lambda: window_classes[0].lpfnWndProc(1, 0xFF, 0, 123), "mouse"),
            (lambda: hooks[13](0, 0x100, ctypes.addressof(keyboard)), "keyboard"),
            (lambda: hooks[14](0, 0x201, ctypes.addressof(mouse)), "mouse"),
        ]:
            state.change(armed=True)
            before = len(stops)
            emit()
            assert state.armed == hand_off
            assert stops[before:] == (
                [] if hand_off else [f"Physical {reason} input; agent paused"]
            )

        # The hotkey must still disarm an active agent with Hand off enabled.
        state.set_hand_off(True)
        state.change(armed=True)
        message._obj.message = 0x0312
        return 1

    messages = iter([first_message, lambda *args: 0])
    user32.GetMessageW.side_effect = lambda *args: next(messages)(*args)
    watch_input(stop, lambda: state.should_pause_on_input(automating=True))
    assert "Stopped with Ctrl+Alt+F12" in stops
    assert not state.armed
