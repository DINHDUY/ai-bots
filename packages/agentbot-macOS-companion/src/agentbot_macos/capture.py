"""Genuine selected-window capture using ScreenCaptureKit, never desktop cropping."""

from __future__ import annotations

import base64
import io
import time
import uuid

from agentbot_macos.results import NotDispatched


def callback_result(invoke, timeout: float = 8):
    from Foundation import NSDate, NSRunLoop

    result = []
    invoke(lambda value, error: result.append((value, error)))
    deadline = time.monotonic() + timeout
    while not result and time.monotonic() < deadline:
        NSRunLoop.currentRunLoop().runUntilDate_(NSDate.dateWithTimeIntervalSinceNow_(0.02))
    if not result:
        raise TimeoutError("Native capture timed out")
    value, error = result[0]
    if error or value is None:
        raise RuntimeError("Native capture unavailable")
    return value


def windows() -> list[dict]:
    import AppKit
    import psutil
    import Quartz

    foreground = AppKit.NSWorkspace.sharedWorkspace().frontmostApplication()
    primary = Quartz.CGDisplayBounds(Quartz.CGMainDisplayID())
    result = []
    info = Quartz.CGWindowListCopyWindowInfo(
        Quartz.kCGWindowListOptionOnScreenOnly | Quartz.kCGWindowListExcludeDesktopElements, 0
    )
    for window in info or []:
        if window.get("kCGWindowLayer") != 0 or not window.get("kCGWindowName"):
            continue
        bounds = window["kCGWindowBounds"]
        x, y, w, h = (float(bounds[k]) for k in ("X", "Y", "Width", "Height"))
        if (
            w < 20
            or h < 20
            or x < primary.origin.x
            or y < primary.origin.y
            or x + w > primary.origin.x + primary.size.width
            or y + h > primary.origin.y + primary.size.height
        ):
            continue
        pid = int(window["kCGWindowOwnerPID"])
        try:
            created = psutil.Process(pid).create_time()
            app = AppKit.NSRunningApplication.runningApplicationWithProcessIdentifier_(pid)
            bundle = str(app.bundleIdentifier() or "") if app else ""
        except (psutil.Error, OSError):
            continue
        result.append(
            {
                "id": str(window["kCGWindowNumber"]),
                "pid": pid,
                "created": created,
                "bundle_id": bundle,
                "name": str(window["kCGWindowName"])[:200],
                "bounds": [x, y, w, h],
                "foreground": bool(foreground and foreground.processIdentifier() == pid),
            }
        )
    return result[:100]


def screenshot(scope: str, window: dict | None, oi) -> dict:
    import AppKit
    import Quartz
    import ScreenCaptureKit as SC

    if not Quartz.CGPreflightScreenCaptureAccess():
        raise NotDispatched("Screen Recording permission required", "permission_required")
    if scope == "display":
        img = oi.screenshot()
        display = Quartz.CGMainDisplayID()
        if img.size != (Quartz.CGDisplayPixelsWide(display), Quartz.CGDisplayPixelsHigh(display)):
            raise NotDispatched("Primary-display capture geometry changed", "stale_target")
        buffer = io.BytesIO()
        img.save(buffer, format="PNG")
        raw, width, height = buffer.getvalue(), img.width, img.height
        rect = Quartz.CGDisplayBounds(Quartz.CGMainDisplayID())
        bounds = [rect.origin.x, rect.origin.y, rect.size.width, rect.size.height]
    else:
        if window is None:
            raise NotDispatched("Select a window locally", "window_required")
        content = callback_result(
            lambda cb: (
                SC.SCShareableContent.getShareableContentExcludingDesktopWindows_onScreenWindowsOnly_completionHandler_(
                    True, True, cb
                )
            )
        )
        target = next((w for w in content.windows() if str(w.windowID()) == window["id"]), None)
        if target is None:
            raise NotDispatched("Selected window unavailable", "stale_target")
        filter_ = SC.SCContentFilter.alloc().initWithDesktopIndependentWindow_(target)
        config = SC.SCStreamConfiguration.alloc().init()
        bounds = window["bounds"]
        scale = float(filter_.pointPixelScale())
        config.setWidth_(round(bounds[2] * scale))
        config.setHeight_(round(bounds[3] * scale))
        config.setShowsCursor_(False)
        image = callback_result(
            lambda cb: (
                SC.SCScreenshotManager.captureImageWithFilter_configuration_completionHandler_(
                    filter_, config, cb
                )
            )
        )
        bitmap = AppKit.NSBitmapImageRep.alloc().initWithCGImage_(image)
        raw = bytes(bitmap.representationUsingType_properties_(AppKit.NSBitmapImageFileTypePNG, {}))
        width, height = int(bitmap.pixelsWide()), int(bitmap.pixelsHigh())
    if len(raw) > 5 * 1024 * 1024:
        raise ValueError("Capture exceeds the image size limit")
    return {
        "id": uuid.uuid4().hex,
        "image": base64.b64encode(raw).decode(),
        "mime": "image/png",
        "width": width,
        "height": height,
        "bounds": bounds,
        "scale_x": width / bounds[2],
        "scale_y": height / bounds[3],
        "display_id": str(Quartz.CGMainDisplayID()),
        "captured_at": time.time(),
    }
