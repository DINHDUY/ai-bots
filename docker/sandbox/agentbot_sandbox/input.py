#!/usr/bin/env python3
"""Bounded desktop input; no command strings or shell interpretation."""

import json
import re
import subprocess
import sys

KEYS = {
    "ArrowLeft": "Left",
    "ArrowRight": "Right",
    "ArrowUp": "Up",
    "ArrowDown": "Down",
    "Enter": "Return",
    "Backspace": "BackSpace",
    "Escape": "Escape",
    "Tab": "Tab",
    "Delete": "Delete",
    "Home": "Home",
    "End": "End",
    "PageUp": "Prior",
    "PageDown": "Next",
    "Shift": "Shift_L",
    "Control": "Control_L",
    "Alt": "Alt_L",
    "Meta": "Super_L",
    " ": "space",
}


def key(value):
    if value in KEYS:
        return KEYS[value]
    if re.fullmatch(r"[a-zA-Z0-9]|F(?:[1-9]|1[0-2])", value):
        return value
    if len(value) == 1 and 32 <= ord(value) <= 0x10FFFF:
        return "U" + format(ord(value), "04x")
    raise ValueError("Unsupported key")


def dispatch(event):
    kind = event["kind"]
    commands = []
    if kind in {"move", "down", "up"}:
        x, y = event["x"], event["y"]
        if not 0 <= x < 1024 or not 0 <= y < 768:
            raise ValueError("Pointer outside desktop")
        commands.append(["mousemove", str(int(x)), str(int(y))])
        if kind != "move":
            button = {"left": "1", "middle": "2", "right": "3"}[
                event.get("button", "left")
            ]
            commands.append(["mousedown" if kind == "down" else "mouseup", button])
    elif kind in {"key_down", "key_up"}:
        commands.append(
            ["keydown" if kind == "key_down" else "keyup", key(event["key"])]
        )
    elif kind == "text":
        if not isinstance(event.get("text"), str) or len(event["text"]) > 1000:
            raise ValueError("Text input exceeds limit")
        commands.append(
            ["type", "--clearmodifiers", "--delay", "0", "--", event["text"]]
        )
    elif kind == "wheel":
        for axis, negative, positive in (("dy", "4", "5"), ("dx", "6", "7")):
            amount = max(-2000, min(2000, event.get(axis, 0)))
            if amount:
                commands.append(
                    [
                        "click",
                        "--repeat",
                        str(min(20, max(1, abs(int(amount)) // 100))),
                        negative if amount < 0 else positive,
                    ]
                )
    elif kind == "release":
        for value in set(event.get("keys", []) + ["Shift", "Control", "Alt", "Meta"]):
            commands.append(["keyup", key(value)])
        commands.extend([["mouseup", button] for button in ("1", "2", "3")])
    else:
        raise ValueError("Unsupported desktop input")
    for command in commands:
        subprocess.run(
            ["xdotool", *command], check=True, capture_output=True, timeout=3
        )


if __name__ == "__main__":
    try:
        dispatch(json.loads(sys.argv[1]))
        print(json.dumps({"ok": True}))
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc)}))
        sys.exit(1)
