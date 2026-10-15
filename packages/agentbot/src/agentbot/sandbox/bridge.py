"""Versioned host bridge messages. No Azure or Docker imports."""

import base64
import hashlib
import hmac
import json
import time
from dataclasses import fields
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from agentbot.interfaces import (
    CaptureImage,
    CaptureResult,
    CommandResult,
    DesktopResult,
)

VERSION = 1
MAX_FRAME = 256 * 1024
MAX_MESSAGE = 48 * 1024 * 1024
CHUNK = 96 * 1024
LEASE_SECONDS = 12
METHODS = {
    "run_command_checked",
    "cancel_commands",
    "browser_click",
    "browser_open_scoped",
    "write_workspace_file_checked",
    "read_workspace_file",
    "list_workspace",
    "workspace_kind",
    "capture",
    "desktop_action",
    "human_input",
    "service_health",
    "workspace_revision",
    "file_revision",
    "files",
    "terminal",
    "sandbox.ensure",
    "sandbox.retire",
    "sandbox.stop",
    "sandbox.inspect",
    "receipt",
}
READS = {
    "service_health",
    "workspace_revision",
    "file_revision",
    "read_workspace_file",
    "list_workspace",
    "workspace_kind",
    "capture",
    "sandbox.inspect",
    "receipt",
}


def packed(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value):
    return hashlib.sha256(packed(value).encode()).hexdigest()


def mutating(method, arguments):
    if method in READS:
        return False
    if method == "files":
        return arguments.get("operation") not in {
            "list",
            "stat",
            "read",
            "changes",
            "revision",
            "preview",
        }
    if method == "terminal":
        return arguments.get("operation") not in {"read", "list", "status", "health"}
    return True


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class HostHello(Strict):
    protocol: Literal[1] = 1
    binding_id: str = Field(min_length=8, max_length=128)
    host_key: str = Field(min_length=32, max_length=128)
    boot_id: str = Field(min_length=8, max_length=128)
    deployment: str = Field(min_length=1, max_length=128)
    channel: Literal["control", "data"] = "control"
    epoch: int = Field(default=0, ge=0)
    sandbox_protocol: Literal[2] = 2
    computer_protocol: Literal[3] = 3
    image: str = Field(max_length=300)
    container_id: str = Field(default="", max_length=128)
    session_id: str = Field(default="", max_length=128)
    generation: int = Field(default=0, ge=0)
    services: dict[str, bool] = Field(default_factory=dict)


class HostRequest(Strict):
    id: str = Field(min_length=8, max_length=128)
    action_id: str = Field(min_length=8, max_length=128)
    binding_id: str = Field(min_length=8, max_length=128)
    deployment: str = Field(min_length=1, max_length=128)
    boot_id: str = Field(min_length=8, max_length=128)
    epoch: int = Field(ge=1)
    session_id: str = Field(min_length=1, max_length=128)
    generation: int = Field(ge=1)
    deadline: float
    method: str = Field(max_length=64)
    arguments: dict[str, Any] = Field(default_factory=dict)
    signature: str = ""

    def sign(self, token):
        self.signature = hmac.new(
            token.encode(),
            packed(self.model_dump(exclude={"signature"})).encode(),
            hashlib.sha256,
        ).hexdigest()
        return self

    def verify(self, token, binding, boot, epoch, deployment):
        signature = hmac.new(
            token.encode(),
            packed(self.model_dump(exclude={"signature"})).encode(),
            hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(signature, self.signature):
            raise ValueError("Invalid bridge signature")
        if (
            self.method not in METHODS
            or not time.time() <= self.deadline <= time.time() + 180
        ):
            raise ValueError("Unsupported or expired bridge request")
        if (self.binding_id, self.boot_id, self.epoch, self.deployment) != (
            binding,
            boot,
            epoch,
            deployment,
        ):
            raise ValueError("Bridge writer fenced")


def encode(value):
    if isinstance(value, CaptureImage):
        return {
            "$type": "capture",
            "data": base64.b64encode(value).decode(),
            "metadata": value.metadata,
        }
    if isinstance(value, bytes):
        return {"$type": "bytes", "data": base64.b64encode(value).decode()}
    if isinstance(value, (CommandResult, DesktopResult)):
        return {
            "$type": type(value).__name__,
            "value": encode(
                {field.name: getattr(value, field.name) for field in fields(value)}
            ),
        }
    if isinstance(value, dict):
        return {key: encode(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [encode(item) for item in value]
    return value


def decode(value, depth=0):
    if depth > 30:
        raise ValueError("Bridge value too deeply nested")
    if isinstance(value, list):
        return [decode(item, depth + 1) for item in value]
    if not isinstance(value, dict):
        return value
    kind = value.get("$type")
    if kind in {"capture", "bytes"}:
        data = base64.b64decode(value["data"], validate=True)
        if len(data) > MAX_MESSAGE:
            raise ValueError("Bridge binary limit exceeded")
        return (
            CaptureImage(CaptureResult(image=data, **value["metadata"]))
            if kind == "capture"
            else data
        )
    if kind in {"CommandResult", "DesktopResult"}:
        return {"CommandResult": CommandResult, "DesktopResult": DesktopResult}[kind](
            **decode(value["value"], depth + 1)
        )
    if kind:
        raise ValueError("Unknown bridge result type")
    return {key: decode(item, depth + 1) for key, item in value.items()}


def frames(message):
    raw = packed(message).encode()
    if len(raw) > MAX_MESSAGE:
        raise ValueError("Bridge response exceeds limit")
    if len(raw) <= MAX_FRAME:
        yield raw.decode()
        return
    identity = message["id"]
    total = (len(raw) + CHUNK - 1) // CHUNK
    checksum = hashlib.sha256(raw).hexdigest()
    for index in range(total):
        yield packed(
            {
                "chunk": identity,
                "index": index,
                "total": total,
                "digest": checksum,
                "data": base64.b64encode(
                    raw[index * CHUNK : (index + 1) * CHUNK]
                ).decode(),
            }
        )


class Assembly:
    def __init__(self):
        self.pending = {}

    def receive(self, raw):
        if not isinstance(raw, str) or len(raw.encode()) > MAX_FRAME:
            raise ValueError("Bridge frame too large")
        value = json.loads(raw)
        if not isinstance(value, dict):
            raise ValueError("Bridge message must be an object")
        if "chunk" not in value:
            return value
        now = time.monotonic()
        self.pending = {
            key: state for key, state in self.pending.items() if now - state[0] < 60
        }
        key, index, total = value["chunk"], value["index"], value["total"]
        if (
            type(index) is not int
            or type(total) is not int
            or not 1 <= total <= (MAX_MESSAGE // CHUNK) + 1
            or not 0 <= index < total
        ):
            raise ValueError("Invalid bridge chunk")
        if key not in self.pending:
            if index != 0 or len(self.pending) >= 4:
                raise ValueError("Bridge assembly limit exceeded")
            self.pending[key] = (now, total, value["digest"], bytearray(), 0)
        created, count, checksum, buffer, expected = self.pending[key]
        if index != expected or total != count or checksum != value["digest"]:
            raise ValueError("Out-of-order bridge chunk")
        chunk = base64.b64decode(value["data"], validate=True)
        if len(chunk) > CHUNK or len(buffer) + len(chunk) > MAX_MESSAGE:
            raise ValueError("Bridge message too large")
        buffer.extend(chunk)
        self.pending[key] = (created, count, checksum, buffer, index + 1)
        if index + 1 == total:
            del self.pending[key]
            if hashlib.sha256(buffer).hexdigest() != checksum:
                raise ValueError("Bridge checksum mismatch")
            result = json.loads(buffer)
            if not isinstance(result, dict) or result.get("id") != key:
                raise ValueError("Invalid assembled message identity")
            return result
        return None
