"""Side-effect-free workspace deletion HTTP contracts."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class DeleteCommand(StrictModel):
    request_id: str = Field(min_length=8, max_length=128, pattern=r"^[a-zA-Z0-9_-]+$")
    preview_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    confirm_name: str = Field(max_length=100)


class EmptyCommand(StrictModel):
    pass


class BotSummary(StrictModel):
    id: str
    name: str


class Blocker(StrictModel):
    code: str
    message: str
    url: str


class RetainedComputer(StrictModel):
    binding_id: str
    provider: str
    resource_id: str
    cleanup_state: str
    url: str


class DeletionPreview(StrictModel):
    workspace_id: str
    workspace_name: str
    bots: list[BotSummary]
    counts: dict[str, int]
    blockers: list[Blocker]
    retained: list[RetainedComputer]
    preview_digest: str


class CleanupStatus(StrictModel):
    state: Literal["pending", "needs_attention", "complete"]
    remaining: int
    bytes_remaining: int
    errors: list[str]


class DeletionResult(StrictModel):
    request_id: str
    workspace_id: str
    workspace_name: str
    deleted_at: str
    counts: dict[str, int]
    retained: list[RetainedComputer]
    cleanup: CleanupStatus


class DeletionHistory(StrictModel):
    items: list[DeletionResult]
    next_cursor: int | None = None


class DeletionContracts(StrictModel):
    command: DeleteCommand
    preview: DeletionPreview
    result: DeletionResult
    history: DeletionHistory
