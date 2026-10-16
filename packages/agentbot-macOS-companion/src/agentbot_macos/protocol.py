"""Versioned, strict companion identities and authenticated execution permits."""

from __future__ import annotations

import hashlib
import hmac
import json
import math
import time
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from agentbot_macos import OI_REVISION, PATCH_VERSION

MAX_FRAME = 8 * 1024 * 1024
MAX_OBSERVATION_AGE = 30


def packed(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value: Any) -> str:
    return hashlib.sha256(packed(value).encode()).hexdigest()


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)


class Hello(Strict):
    protocol: Literal[1] = 1
    device_id: str = Field(min_length=1, max_length=128)
    epoch: str = Field(min_length=8, max_length=128)
    console_session: str = Field(min_length=1, max_length=200)
    name: str = Field(min_length=1, max_length=100)
    revision: int = Field(ge=0)
    sharing: bool = False
    armed: bool = False
    ready: bool = False
    screen_recording: bool = False
    accessibility: bool = False
    reason: str = Field(default="", max_length=300)
    oi_revision: Literal["5a4f706223507fc9d9eb2239cced85385fcb1308"] = OI_REVISION
    patch_version: Literal[1] = PATCH_VERSION
    scope: Literal["window", "display"] = "window"


class Envelope(Strict):
    protocol: Literal[1] = 1
    id: str = Field(min_length=8, max_length=128)
    method: Literal[
        "health",
        "capabilities",
        "observe",
        "capture",
        "detect_ui",
        "planner",
        "execute",
        "action_status",
        "cancel",
        "local_stop",
    ]
    arguments: dict[str, Any] = Field(default_factory=dict)
    deadline: float


class PermitBase(Strict):
    action_id: str = Field(min_length=8, max_length=128)
    run_id: str = Field(min_length=8, max_length=128)
    session_id: str = Field(min_length=8, max_length=128)
    device_id: str = Field(min_length=1, max_length=128)
    console_session: str = Field(min_length=1, max_length=200)
    generation: int = Field(ge=1)
    epoch: str = Field(min_length=8, max_length=128)
    local_revision: int = Field(ge=0)
    expires_at: float
    signature: str = Field(default="", max_length=64)

    def sign(self, key: str):
        self.signature = hmac.new(
            key.encode(), packed(self.model_dump(exclude={"signature"})).encode(), hashlib.sha256
        ).hexdigest()
        return self

    def verify(self, key: str, hello: Hello, now: float | None = None) -> None:
        expected = hmac.new(
            key.encode(), packed(self.model_dump(exclude={"signature"})).encode(), hashlib.sha256
        ).hexdigest()
        now = time.time() if now is None else now
        if not hmac.compare_digest(expected, self.signature):
            raise ValueError("Invalid execution permit")
        if not math.isfinite(self.expires_at) or not now <= self.expires_at <= now + 15:
            raise ValueError("Execution permit expired")
        if (self.device_id, self.console_session, self.epoch, self.local_revision) != (
            hello.device_id,
            hello.console_session,
            hello.epoch,
            hello.revision,
        ):
            raise ValueError("Device, session or local consent changed")
        if not (hello.ready and hello.sharing and hello.armed):
            raise ValueError("Local sharing/control is off")
