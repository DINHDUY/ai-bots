"""Bounded read-only AX observation. Handles never leave the native process."""

from __future__ import annotations

import time
from collections import deque

from agentbot_macos.results import NotDispatched

MAX_ELEMENTS = 4096
MAX_CONTROLS = 300
INSPECTION_SECONDS = 3
TEXT_ROLES = {"AXTextField", "AXTextArea", "AXComboBox"}
LAYOUT_ROLES = {"AXWindow", "AXGroup", "AXSplitGroup", "AXScrollArea", "AXSplitter"}


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


def _checked_attribute(element, name, default=None):
    """Missing optional attributes are normal; failed tree reads are not leaves."""
    import ApplicationServices as AX

    error, value = AX.AXUIElementCopyAttributeValue(element, name, None)
    if error == 0 and (name != "AXRole" or isinstance(value, str) and value):
        return value
    if name != "AXRole" and error in (-25205, -25212):  # Unsupported / no value.
        return default
    raise NotDispatched(
        "Accessibility tree could not be read completely; retry or choose another window",
        "unsupported_surface",
    )


def _check_deadline(deadline: float) -> None:
    if time.monotonic() >= deadline:
        raise NotDispatched(
            "AX inspection timed out; close busy windows or share one window",
            "unsupported_surface",
        )


def _scan(root, deadline: float) -> list[tuple]:
    pending = deque([root])
    seen = {root}
    elements = []
    while pending:
        _check_deadline(deadline)
        element = pending.popleft()
        role = str(_checked_attribute(element, "AXRole"))
        subrole = str(
            _checked_attribute(element, "AXSubrole", "")
            if role in TEXT_ROLES
            else attribute(element, "AXSubrole", "")
        )
        if role == "AXSecureTextField" or subrole == "AXSecureTextField":
            raise NotDispatched("Secure input is present; choose another window", "secure_surface")
        elements.append((element, role))
        for child in _checked_attribute(element, "AXChildren", []) or []:
            _check_deadline(deadline)
            if child in seen:
                continue
            if len(seen) >= MAX_ELEMENTS:
                raise NotDispatched(
                    f"AX inspection exceeded {MAX_ELEMENTS} elements; share a simpler window",
                    "unsupported_surface",
                )
            seen.add(child)
            pending.append(child)
    _check_deadline(deadline)
    return elements


def inspect(
    window: dict, *, include_controls: bool = True, deadline: float | None = None
) -> tuple[list[dict], dict]:
    import ApplicationServices as AX

    if deadline is None:
        deadline = time.monotonic() + INSPECTION_SECONDS
    _check_deadline(deadline)
    elements = _scan(window_element(window), deadline)
    controls, handles = [], {}
    if not include_controls:
        return controls, handles
    # Keep text targets and useful controls ahead of layout containers. The full
    # tree has already passed the secure-field scan, even beyond the output cap.
    elements.sort(key=lambda item: (item[1] not in TEXT_ROLES, item[1] in LAYOUT_ROLES))
    for element, role in elements:
        _check_deadline(deadline)
        rect = bounds(element)
        if rect:
            cid = str(len(controls) + 1)
            text_role = role in TEXT_ROLES
            err, writable = (
                AX.AXUIElementIsAttributeSettable(element, "AXValue", None)
                if text_role
                else (0, False)
            )
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
            if len(controls) >= MAX_CONTROLS:
                break
    _check_deadline(deadline)
    return controls, handles


def set_text(element, text: str) -> bool:
    import ApplicationServices as AX

    if AX.AXUIElementSetAttributeValue(element, "AXValue", text):
        raise RuntimeError("AX text write failed; no keystroke fallback")
    return attribute(element, "AXValue") == text
