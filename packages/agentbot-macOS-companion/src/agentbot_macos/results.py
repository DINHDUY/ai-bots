"""Execution evidence distinguishes input dispatch from verified effects."""

from typing import Literal

from pydantic import Field, model_validator

from agentbot_macos.protocol import Strict


class ActionResult(Strict):
    ok: bool = False
    dispatched: bool = False
    effect_observed: bool = False
    outcome_unknown: bool = False
    code: str = Field(default="", max_length=100)
    text: str = Field(default="", max_length=1000)
    capture_id: str | None = None

    @model_validator(mode="after")
    def evidence_consistent(self):
        if self.outcome_unknown and (self.ok or self.effect_observed):
            raise ValueError("Unknown effects cannot be successful or verified")
        return self


class NotDispatched(RuntimeError):
    def __init__(self, message: str, code: str = "not_dispatched"):
        super().__init__(message)
        self.code = code

    def result(self) -> dict:
        return ActionResult(code=self.code, text=str(self)[:1000]).model_dump()


def unknown(reason: str) -> dict:
    return ActionResult(
        dispatched=True, outcome_unknown=True, code="outcome_unknown", text=reason[:1000]
    ).model_dump()


class TaskResult(Strict):
    task_id: str
    state: Literal["running", "completed", "failed", "cancelled", "outcome_unknown"]
    text: str = Field(default="", max_length=4000)
    effect_observed: bool = False
    retryable: Literal[False] = False


class TaskReceipt(TaskResult):
    request_id: str
    run_id: str
