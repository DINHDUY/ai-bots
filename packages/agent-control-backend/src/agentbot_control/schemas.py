"""Validated v2 commands; independent of HTTP handlers."""

from typing import Literal

from pydantic import AliasChoices, BaseModel, ConfigDict, Field


class Command(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    request_id: str = Field(min_length=8, max_length=128, pattern=r"^[a-zA-Z0-9_-]+$")


class StartRun(Command):
    prompt: str = Field(min_length=1, max_length=32000)
    attachment_ids: list[str] = Field(default_factory=list, max_length=10)


class Decision(Command):
    decision: Literal["approve", "deny"]
    revision: int = Field(
        default=1, ge=1, validation_alias=AliasChoices("expected_revision", "revision")
    )


class CloseComputer(Command):
    session_id: str | None = None


class CreatePolicy(Command):
    approval_id: str = Field(min_length=1, max_length=128)
    ttl_seconds: int = Field(default=86400, ge=60, le=2592000)


ACTIVE_RUNS = ("preparing", "running", "awaiting_approval", "stopping")
CAPABILITIES = {
    "protocol_version": 2,
    "durable_runs": True,
    "replay": True,
    "persistent_policies": True,
    "structured_actions": True,
    "autopilot": True,
    "remote_control": True,
    "filesystem": True,
    "pty": True,
    "lifecycle": True,
    "workspaces": True,
    "groups": True,
    "toolkit": True,
    "routines": True,
    "health": True,
    "capture_metadata": True,
    "capture_retention": True,
}


class Conflict(Exception):
    """A domain rejection with stable scheduling semantics and independent display text."""

    def __init__(self, message: str, *, code: str = "conflict") -> None:
        super().__init__(message)
        self.code = code

    @property
    def waiting(self) -> bool:
        return self.code in {"bot_busy", "computer_unavailable", "human_control", "credential_required", "recovery_required", "capacity_limit", "worker_unavailable"}
