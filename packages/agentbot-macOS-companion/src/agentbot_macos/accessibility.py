"""Bounded read-only AX observation. Handles never leave the native process."""

from __future__ import annotations

import time

from agentbot_macos.results import NotDispatched


def attribute(element, name, default=None):
    import ApplicationServices as AX

    error, value = AX.AXUIElementCopyAttributeValue(element, name, None)
    return value if error == 0 else default


def bounds(element) -> list[float] | None:
    import ApplicationServices as AX

    point, size = attribute(element, "AXPosition"), attribute(element, "AXSize")
    if point is None or size is None:
        return None
    ok1, p = AX.AXValueGetValue(point, AX.kAXValueCGPointType, None)
    ok2, s = AX.AXValueGetValue(size, AX.kAXValueCGSizeType, None)
    return [float(p.x), float(p.y), float(s.width), float(s.height)] if ok1 and ok2 else None


def window_element(window: dict):
    import ApplicationServices as AX

    app = AX.AXUIElementCreateApplication(window["pid"])
    AX.AXUIElementSetMessagingTimeout(app, 1.0)
    matches = []
    for item in attribute(app, "AXWindows", [])[:100]:
        rect = bounds(item)
        if rect and all(abs(a - b) < 2 for a, b in zip(rect, window["bounds"], strict=True)):
            matches.append(item)
    if len(matches) != 1:
        raise NotDispatched("Selected AX window is unavailable or ambiguous", "stale_target")
    return matches[0]


def inspect(window: dict) -> tuple[list[dict], dict]:
    import ApplicationServices as AX

    root = window_element(window)
    pending = [root]
    controls, handles = [], {}
    deadline = time.monotonic() + 3
    while pending and len(controls) < 300 and time.monotonic() < deadline:
        element = pending.pop(0)
        role = str(attribute(element, "AXRole", ""))
        subrole = str(attribute(element, "AXSubrole", ""))
        if subrole == "AXSecureTextField":
            raise NotDispatched("Secure input is present; choose another window", "secure_surface")
        rect = bounds(element)
        if rect:
            cid = str(len(controls) + 1)
            err, writable = AX.AXUIElementIsAttributeSettable(element, "AXValue", None)
            text_role = role in {"AXTextField", "AXTextArea", "AXComboBox"}
            record = {
                "id": cid,
                "role": role,
                "label": str(
                    attribute(element, "AXTitle", "") or attribute(element, "AXDescription", "")
                )[:300],
                "bounds": rect,
                "enabled": bool(attribute(element, "AXEnabled", True)),
                "focused": bool(attribute(element, "AXFocused", False)),
                "editable": text_role,
                "writable": bool(text_role and err == 0 and writable),
                "source": "accessibility",
            }
            observed_value = attribute(element, "AXValue")
            if isinstance(observed_value, (str, int, float, bool)):
                record["value"] = str(observed_value)[:16000]
            controls.append(record)
            handles[cid] = element
        pending.extend(list(attribute(element, "AXChildren", []))[: 300 - len(controls)])
    if pending:
        raise NotDispatched(
            "AX inspection exceeded its bound; choose a simpler window", "unsupported_surface"
        )
    return controls, handles


def set_text(element, text: str) -> bool:
    import ApplicationServices as AX

    if AX.AXUIElementSetAttributeValue(element, "AXValue", text):
        raise RuntimeError("AX text write failed; no keystroke fallback")
    return attribute(element, "AXValue") == text
