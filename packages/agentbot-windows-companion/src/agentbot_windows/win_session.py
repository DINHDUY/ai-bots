"""Small native session/credential boundary; imported only on Windows."""

import ctypes
import os
import threading
import uuid
from ctypes import wintypes

from .mouse_activity import MouseActivity


class RawInputHeader(ctypes.Structure):
    _fields_ = [
        ("kind", ctypes.c_uint32),
        ("size", ctypes.c_uint32),
        ("device", ctypes.c_void_p),
        ("parameter", ctypes.c_size_t),
    ]


class RawMouse(ctypes.Structure):
    _fields_ = [
        ("flags", ctypes.c_uint16),
        ("buttons", ctypes.c_uint32),
        ("raw_buttons", ctypes.c_uint32),
        ("x", ctypes.c_int32),
        ("y", ctypes.c_int32),
        ("extra", ctypes.c_uint32),
    ]


class RawMouseInput(ctypes.Structure):
    _fields_ = [("header", RawInputHeader), ("mouse", RawMouse)]


def mouse_activity_from_event(user32, event, activity):
    packet = RawMouseInput()
    size = wintypes.UINT(ctypes.sizeof(packet))
    copied = user32.GetRawInputData(
        event,
        0x10000003,  # RID_INPUT: inspect mouse data, not just its header.
        ctypes.byref(packet),
        ctypes.byref(size),
        ctypes.sizeof(RawInputHeader),
    )
    if (
        copied != ctypes.sizeof(packet)
        or packet.header.kind != 0
        or not packet.header.device
    ):
        return False
    mouse = packet.mouse
    return activity.observe(
        packet.header.device, mouse.flags, mouse.buttons & 0xFFFF,
        mouse.buttons >> 16, mouse.x, mouse.y,
    )


def desktop_lock():
    """One companion per interactive Windows session, across pairing profiles."""
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
    kernel32.CreateMutexW.restype = wintypes.HANDLE
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel32.CreateMutexW(None, False, "Local\\AgentControlWindowsDesktop")
    if not handle:
        raise RuntimeError("Cannot reserve this Windows desktop")
    if ctypes.get_last_error() == 183:
        kernel32.CloseHandle(handle)
        raise RuntimeError("A companion is already running in this Windows session")
    return lambda: kernel32.CloseHandle(handle)


def worker_job(pid):
    """Kill only this owned worker if its supervising companion exits."""
    import win32api
    import win32job

    job = win32job.CreateJobObject(None, "Local\\AgentControlWorker-" + uuid.uuid4().hex)
    try:
        limits = win32job.QueryInformationJobObject(
            job, win32job.JobObjectExtendedLimitInformation
        )
        # Apps launched by an approved task must survive worker cancellation.
        limits["BasicLimitInformation"]["LimitFlags"] = (
            win32job.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            | win32job.JOB_OBJECT_LIMIT_SILENT_BREAKAWAY_OK
        )
        win32job.SetInformationJobObject(
            job, win32job.JobObjectExtendedLimitInformation, limits
        )
        process = win32api.OpenProcess(0x100 | 0x1 | 0x400, False, pid)
        try:
            win32job.AssignProcessToJobObject(job, process)
        finally:
            process.Close()
        return job
    except BaseException:
        job.Close()
        raise


def session_check():
    import win32ts

    sid = wintypes.DWORD()
    ctypes.windll.kernel32.ProcessIdToSessionId(os.getpid(), ctypes.byref(sid))
    identity = f"{os.environ.get('USERNAME', 'user')}:{sid.value}"
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.OpenInputDesktop.restype = wintypes.HANDLE
    user32.OpenInputDesktop.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    user32.CloseDesktop.argtypes = [wintypes.HANDLE]
    user32.GetUserObjectInformationW.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
    ]
    handle = user32.OpenInputDesktop(0, False, 0x101)
    if not handle:
        return False, identity, "Unlock Windows or complete the secure-desktop prompt"
    try:
        name, size = ctypes.create_unicode_buffer(256), wintypes.DWORD()
        if (
            not user32.GetUserObjectInformationW(
                handle, 2, name, ctypes.sizeof(name), ctypes.byref(size)
            )
            or name.value != "Default"
        ):
            return False, identity, "Windows secure desktop is active"
        if (
            win32ts.WTSQuerySessionInformation(None, sid.value, win32ts.WTSConnectState)
            != win32ts.WTSActive
        ):
            return False, identity, "Windows session disconnected"
    finally:
        user32.CloseDesktop(handle)
    return True, identity, ""


def protect(data):
    import win32crypt

    return win32crypt.CryptProtectData(
        data, "Agent Control companion", None, None, None, 0
    )


def unprotect(data):
    import win32crypt

    return win32crypt.CryptUnprotectData(data, None, None, None, 0)[1]


def watch_input(on_takeover, should_pause_on_input):
    """Apply the physical-input policy; Ctrl+Alt+F12 always stops the worker."""
    ready = threading.Event()

    def run():
        import win32gui

        user32 = ctypes.WinDLL("user32", use_last_error=True)
        callback_type = ctypes.WINFUNCTYPE(
            ctypes.c_ssize_t, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM
        )
        user32.SetWindowsHookExW.restype = wintypes.HANDLE
        user32.SetWindowsHookExW.argtypes = [
            ctypes.c_int,
            callback_type,
            wintypes.HINSTANCE,
            wintypes.DWORD,
        ]
        user32.CallNextHookEx.restype = ctypes.c_ssize_t
        user32.CallNextHookEx.argtypes = [
            wintypes.HANDLE,
            ctypes.c_int,
            wintypes.WPARAM,
            wintypes.LPARAM,
        ]

        class Keyboard(ctypes.Structure):
            _fields_ = [
                ("vk", wintypes.DWORD),
                ("scan", wintypes.DWORD),
                ("flags", wintypes.DWORD),
                ("time", wintypes.DWORD),
                ("extra", ctypes.c_size_t),
            ]

        class Mouse(ctypes.Structure):
            _fields_ = [
                ("point", wintypes.POINT),
                ("data", wintypes.DWORD),
                ("flags", wintypes.DWORD),
                ("time", wintypes.DWORD),
                ("extra", ctypes.c_size_t),
            ]

        class RawDevice(ctypes.Structure):
            _fields_ = [
                ("page", wintypes.USHORT),
                ("usage", wintypes.USHORT),
                ("flags", wintypes.DWORD),
                ("target", wintypes.HWND),
            ]

        user32.GetRawInputData.argtypes = [
            wintypes.HANDLE,
            wintypes.UINT,
            ctypes.c_void_p,
            ctypes.POINTER(wintypes.UINT),
            wintypes.UINT,
        ]
        user32.RegisterRawInputDevices.argtypes = [
            ctypes.POINTER(RawDevice),
            wintypes.UINT,
            wintypes.UINT,
        ]

        activity = MouseActivity()

        def raw_mouse(hwnd, message, wparam, lparam):
            if message == 0xFF:
                # Keep absolute-position baselines current while idle too.
                changed = mouse_activity_from_event(user32, lparam, activity)
                if changed and should_pause_on_input():
                    on_takeover("Physical mouse input; agent paused")
            return win32gui.DefWindowProc(hwnd, message, wparam, lparam)

        # Raw hardware input distinguishes mouse movement from SetCursorPos,
        # which UI libraries may generate without an injected low-level flag.
        window_class = win32gui.WNDCLASS()
        window_class.lpszClassName = "AgentControlInputWatcher" + str(os.getpid())
        window_class.lpfnWndProc = raw_mouse
        atom = win32gui.RegisterClass(window_class)
        window = win32gui.CreateWindowEx(0, atom, "", 0, 0, 0, 0, 0, -3, 0, None, None)
        raw_device = RawDevice(1, 2, 0x100, window)
        raw_ready = user32.RegisterRawInputDevices(
            ctypes.byref(raw_device), 1, ctypes.sizeof(RawDevice)
        )

        @callback_type
        def keyboard(code, event, data):
            if (
                code >= 0
                and event in {0x100, 0x104}
                and should_pause_on_input()
                and not ctypes.cast(data, ctypes.POINTER(Keyboard)).contents.flags
                & 0x10
            ):
                on_takeover("Physical keyboard input; agent paused")
            return user32.CallNextHookEx(None, code, event, data)

        @callback_type
        def mouse(code, event, data):
            if (
                code >= 0
                and event in {0x201, 0x204, 0x207, 0x20A}
                and should_pause_on_input()
                and not ctypes.cast(data, ctypes.POINTER(Mouse)).contents.flags & 1
            ):
                on_takeover("Physical mouse input; agent paused")
            return user32.CallNextHookEx(None, code, event, data)

        hooks = [
            user32.SetWindowsHookExW(13, keyboard, None, 0),
            user32.SetWindowsHookExW(14, mouse, None, 0),
        ]
        if (
            not raw_ready
            or not all(hooks)
            or not user32.RegisterHotKey(None, 1, 0x0003, 0x7B)
        ):
            on_takeover("Local input watcher could not start; control disabled")
            return
        ready.set()
        message = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(message), None, 0, 0) > 0:
            if message.message == 0x0312:
                on_takeover("Stopped with Ctrl+Alt+F12")
            user32.TranslateMessage(ctypes.byref(message))
            user32.DispatchMessageW(ctypes.byref(message))
        ready.clear()
        on_takeover("Local input watcher stopped")

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    return ready
