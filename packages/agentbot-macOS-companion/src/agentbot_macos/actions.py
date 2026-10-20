"""Complete model-to-native allowlist; no dynamic method names or command strings."""

from __future__ import annotations

import math
import unicodedata
from typing import Any, Literal

from pydantic import Field, model_validator

from agentbot_macos.protocol import PermitBase, Strict

APPLICATIONS = {"com.apple.TextEdit", "com.apple.calculator", "com.apple.Safari"}
KEYS = {
    "enter",
    "tab",
    "esc",
    "backspace",
    "delete",
    "home",
    "end",
    "left",
    "right",
    "up",
    "down",
    "pageup",
    "pagedown",
    "space",
}
MODIFIERS = {"command", "ctrl", "alt", "shift"}
FUNCTIONS = (
    "focus_window",
    "launch_app",
    "click",
    "move",
    "scroll",
    "drag",
    "set_text",
    "type_text",
    "key_input",
    "wait",
)


class MacAction(Strict):
    function: Literal[
        "focus_window",
        "launch_app",
        "click",
        "move",
        "scroll",
        "drag",
        "set_text",
        "type_text",
        "key_input",
        "wait",
    ]
    observation_id: str = Field(min_length=8, max_length=128)
    window_id: str = Field(max_length=128)
    control_id: str = Field(default="", max_length=128)
    arguments: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_arguments(self):
        allowed = {
            "focus_window": set(),
            "launch_app": {"bundle_id"},
            "click": {"x", "y", "button", "double"},
            "move": {"x", "y"},
            "scroll": {"amount"},
            "drag": {"x", "y", "to_x", "to_y", "duration"},
            "set_text": {"text"},
            "type_text": {"text"},
            "key_input": {"keys"},
            "wait": {"seconds"},
        }[self.function]
        a = self.arguments
        if set(a) - allowed:
            raise ValueError("Unsupported action arguments")
        if self.function not in {"launch_app", "wait"} and not self.window_id:
            raise ValueError("An observed window is required")
        if self.function in {"set_text", "type_text"}:
            text = a.get("text")
            limit = 2000 if self.function == "type_text" else 16000
            if not self.control_id or not isinstance(text, str) or not 1 <= len(text) <= limit:
                raise ValueError("A text control and bounded literal text are required")
            if any(unicodedata.category(c) in {"Cc", "Cs"} for c in text):
                raise ValueError(
                    "Text must be literal single-line Unicode without control characters"
                )
        if self.function == "launch_app" and a.get("bundle_id") not in APPLICATIONS:
            raise ValueError("Application is not allowlisted")
        if self.function == "key_input":
            keys = a.get("keys")
            if (
                not isinstance(keys, list)
                or not 1 <= len(keys) <= 4
                or any(not isinstance(k, str) for k in keys)
            ):
                raise ValueError("Use one key or modifier chord")
            if len(set(keys)) != len(keys) or any(k not in MODIFIERS for k in keys[:-1]):
                raise ValueError("Invalid modifiers")
            if keys[-1] not in KEYS and not (
                len(keys[-1]) == 1 and keys[-1] in "abcdefghijklmnopqrstuvwxyz0123456789"
            ):
                raise ValueError("Unsupported key")
        coordinate_keys = []
        if self.function in {"click", "move", "drag"} and not (
            self.function == "click" and self.control_id and "x" not in a and "y" not in a
        ):
            coordinate_keys = ["x", "y"]
        if self.function == "drag":
            coordinate_keys += ["to_x", "to_y"]
        for k in coordinate_keys:
            if type(a.get(k)) not in (float, int) or not math.isfinite(a[k]) or not 0 <= a[k] <= 1:
                raise ValueError("Coordinates must be finite normalized window coordinates")
        if (
            a.get("button", "left") not in {"left", "right"}
            or type(a.get("double", False)) is not bool
        ):
            raise ValueError("Invalid click parameters")
        if self.function == "scroll" and (
            type(a.get("amount")) is not int or not -10 <= a["amount"] <= 10 or not a["amount"]
        ):
            raise ValueError("Scroll must be a nonzero integer between -10 and 10")
        for key, maximum in (("duration", 2), ("seconds", 5)):
            if (key == "duration" and self.function == "drag") or (
                key == "seconds" and self.function == "wait"
            ):
                if (
                    type(a.get(key)) not in (int, float)
                    or not math.isfinite(a[key])
                    or not 0 < a[key] <= maximum
                ):
                    raise ValueError(f"{key} must be between zero and {maximum}")
        return self


class Permit(PermitBase):
    action: MacAction
