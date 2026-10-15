"""The complete allowlist between a model proposal and the Windows executor."""

from __future__ import annotations

import hashlib
import hmac
import json
import math
import re
import time
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

MAX_FRAME = 8 * 1024 * 1024
MAX_OBSERVATION_AGE = 30
FUNCTIONS = (
    "select_application_window",
    "click_input",
    "set_edit_text",
    "type_text",
    "keyboard_input",
    "wheel_mouse_input",
    "click_on_coordinates",
    "launch_app",
)


def packed(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value: Any) -> str:
    return hashlib.sha256(packed(value).encode()).hexdigest()


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class WindowsAction(Strict):
    function: Literal[
        "select_application_window",
        "click_input",
        "set_edit_text",
        "type_text",
        "keyboard_input",
        "wheel_mouse_input",
        "click_on_coordinates",
        "launch_app",
    ]
    observation_id: str = Field(min_length=8, max_length=128)
    window_id: str = Field(max_length=128)
    control_id: str = Field(default="", max_length=128)
    arguments: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def check_arguments(self):
        allowed = {
            "select_application_window": set(),
            "click_input": {"button", "double"},
            "set_edit_text": {"text"},
            "type_text": {"text"},
            "keyboard_input": {"keys"},
            "wheel_mouse_input": {"wheel_dist"},
            "click_on_coordinates": {"x", "y", "button", "double"},
            "launch_app": {"app"},
        }[self.function]
        a = self.arguments
        if set(a) - allowed:
            raise ValueError("Unsupported action arguments")
        if self.function == "set_edit_text":
            if not isinstance(a.get("text"), str) or len(a["text"]) > 16000:
                raise ValueError("Text must be a string of at most 16000 characters")
        if self.function == "type_text":
            from .text_input import validate_text

            validate_text(a.get("text"))
            if not self.control_id:
                raise ValueError("Literal typing requires an observed editor")
        if self.function == "keyboard_input":
            # UFO interprets braces and modifiers; constrain the grammar, not Python.
            keys = a.get("keys")
            if not isinstance(keys, str) or not 1 <= len(keys) <= 120:
                raise ValueError("Invalid keyboard sequence")
            if any(c in keys for c in ("\n", "\r", "\x00")):
                raise ValueError("Invalid keyboard sequence")
            if not re.fullmatch(
                r"[\^%+]*(?:[a-zA-Z0-9]|\{(?:ENTER|TAB|ESC|ESCAPE|BACKSPACE|DELETE|HOME|END|LEFT|RIGHT|UP|DOWN|PGUP|PGDN|F[1-9]|F1[0-2])\})",
                keys,
            ):
                raise ValueError(
                    "Use one bounded navigation key or shortcut; enter text with set_edit_text or type_text"
                )
        if self.function == "wheel_mouse_input":
            if type(a.get("wheel_dist")) is not int or not -10 <= a["wheel_dist"] <= 10:
                raise ValueError("Scroll must be between -10 and 10")
        if self.function == "click_on_coordinates":
            for key in ("x", "y"):
                if (
                    type(a.get(key)) not in (int, float)
                    or not math.isfinite(a[key])
                    or not 0 <= a[key] <= 1
                ):
                    raise ValueError(
                        "Coordinates must be finite normalized window coordinates"
                    )
        if a.get("button", "left") not in {"left", "right", "middle"}:
            raise ValueError("Invalid button")
        if type(a.get("double", False)) is not bool:
            raise ValueError("Invalid double-click flag")
        if self.function == "launch_app" and a.get("app") not in {
            "notepad",
            "calculator",
        }:
            raise ValueError("Application is not allowlisted")
        return self


class Permit(Strict):
    action_id: str = Field(min_length=8, max_length=128)
    session_id: str = Field(min_length=8, max_length=128)
    generation: int = Field(ge=1)
    epoch: str = Field(min_length=8, max_length=128)
    local_revision: int = Field(ge=0)
    expires_at: float
    action: WindowsAction
    signature: str = ""

    def sign(self, key: str):
        self.signature = hmac.new(
            key.encode(),
            packed(self.model_dump(exclude={"signature"})).encode(),
            hashlib.sha256,
        ).hexdigest()
        return self

    def verify(self, key: str, epoch: str, local_revision: int, now=None):
        expected = hmac.new(
            key.encode(),
            packed(self.model_dump(exclude={"signature"})).encode(),
            hashlib.sha256,
        ).hexdigest()
        now = time.time() if now is None else now
        if not hmac.compare_digest(expected, self.signature):
            raise ValueError("Invalid execution permit")
        if not math.isfinite(self.expires_at) or not now <= self.expires_at <= now + 15:
            raise ValueError("Execution permit expired")
        if self.epoch != epoch or self.local_revision != local_revision:
            raise ValueError("Local control changed; permit fenced")


class Hello(Strict):
    protocol: Literal[1] = 1
    epoch: str = Field(min_length=8, max_length=128)
    windows_session: str = Field(min_length=1, max_length=200)
    name: str = Field(min_length=1, max_length=100)
    revision: int = Field(ge=0)
    sharing: bool = False
    armed: bool = False
    ready: bool = False
    reason: str = Field(default="", max_length=300)
    ufo_revision: str = Field(max_length=64)
