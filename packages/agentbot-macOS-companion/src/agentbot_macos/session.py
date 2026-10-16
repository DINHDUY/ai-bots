"""Read-only macOS permission/session checks. Never requests TCC consent."""

from __future__ import annotations

import ctypes
import os
import platform
import sys


def permissions() -> dict:
    if sys.platform != "darwin":
        return {
            "ready": False,
            "screen_recording": False,
            "accessibility": False,
            "console_session": "unsupported",
            "reason": "Native runtime requires macOS",
        }
    import ApplicationServices as AX
    import Quartz

    screen = bool(Quartz.CGPreflightScreenCaptureAccess())
    accessibility = bool(AX.AXIsProcessTrusted())
    info = Quartz.CGSessionCopyCurrentDictionary() or {}
    active = bool(info.get("kCGSessionOnConsoleKey")) and bool(info.get("kCGSessionLoginDoneKey"))
    active = active and not info.get("CGSSessionScreenIsLocked", False)
    own = int(info.get("kCGSessionUserIDKey", -1)) == os.getuid()
    session = f"{os.getuid()}:{info.get('kCGSessionAuditIDKey', 'unknown')}"
    carbon = ctypes.CDLL("/System/Library/Frameworks/Carbon.framework/Carbon")
    carbon.IsSecureEventInputEnabled.restype = ctypes.c_bool
    secure = bool(carbon.IsSecureEventInputEnabled())
    reasons = []
    if secure:
        reasons.append("Secure input is active")
    if not screen:
        reasons.append("Screen Recording permission required")
    if not accessibility:
        reasons.append("Accessibility permission required")
    if not active or not own:
        reasons.append("An unlocked console session is required")
    return {
        "ready": screen and accessibility and active and own and not secure,
        "screen_recording": screen,
        "accessibility": accessibility,
        "console_session": session,
        "reason": "; ".join(reasons),
        "os_version": platform.mac_ver()[0],
    }


def require_session(expected: str | None = None) -> dict:
    from agentbot_macos.results import NotDispatched

    state = permissions()
    if not state["ready"] or (expected is not None and state["console_session"] != expected):
        raise NotDispatched(state["reason"] or "Console session changed", "session_unavailable")
    return state
