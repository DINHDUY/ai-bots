"""Portable TaskStar assignment bridge; no UFO imports in the backend process."""

from __future__ import annotations

import hashlib
from typing import Any

from pydantic import Field, model_validator

from agentbot_macos.protocol import Strict, packed


class TaskAssignment(Strict):
    producer: str = Field(
        default="galaxy", min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_.-]+$"
    )
    task_id: str = Field(min_length=1, max_length=128)
    device_id: str = Field(min_length=1, max_length=128)
    task_description: str = Field(min_length=1, max_length=20000)
    task_data: dict[str, Any] = Field(default_factory=dict)
    timeout: float = Field(default=900.0, gt=0, le=900)

    @model_validator(mode="after")
    def bounded_data(self):
        def check(value, depth=0):
            if depth > 5:
                raise ValueError("Task data is too deeply nested")
            if value is None or type(value) in (str, int, float, bool):
                return
            if isinstance(value, list):
                if len(value) > 100:
                    raise ValueError("Task data list exceeds limit")
                for item in value:
                    check(item, depth + 1)
                return
            if isinstance(value, dict):
                if len(value) > 100 or any(not isinstance(k, str) or len(k) > 100 for k in value):
                    raise ValueError("Invalid task data object")
                for item in value.values():
                    check(item, depth + 1)
                return
            raise ValueError("Task data must be JSON values")

        check(self.task_data)
        if len(packed(self.task_data).encode()) > 16000:
            raise ValueError("Task data exceeds limit")
        if len(self.task_description) + len(packed(self.task_data)) + 32 > 32000:
            raise ValueError("Combined task description and data exceed limit")
        return self

    @property
    def request_id(self):
        return (
            "taskstar_" + hashlib.sha256((self.producer + "\0" + self.task_id).encode()).hexdigest()
        )


class TaskStarBridge:
    """Pass this object to the pinned TaskStar.execute(device_manager) seam.

    The supplied HTTP client must be authenticated as the bot owner. Transport
    retries retain the task identity; they never submit a new UI execution.
    """

    def __init__(self, client, bot_id: str, *, producer="galaxy", result_factory=None):
        self.client, self.bot_id, self.producer = client, bot_id, producer
        self.result_factory = result_factory

    async def assign_task_to_device(
        self,
        task_id: str,
        device_id: str,
        task_description: str,
        task_data: dict,
        timeout: float = 900,
    ):
        assignment = TaskAssignment(
            producer=self.producer,
            task_id=task_id,
            device_id=device_id,
            task_description=task_description,
            task_data=task_data,
            timeout=min(float(timeout), 900.0),
        )
        route = f"/api/bots/{self.bot_id}/taskstars"
        from agentbot_macos.task_transport import submit

        result = await submit(self.client, route, assignment)
        if self.result_factory:
            return self.result_factory(task_id, result)
        # Only an explicitly installed bridge environment needs upstream objects.
        from galaxy.constellation.enums import TaskStatus
        from galaxy.core.types import ExecutionResult

        status = {"completed": TaskStatus.COMPLETED, "cancelled": TaskStatus.CANCELLED}.get(
            result["state"], TaskStatus.FAILED
        )
        return ExecutionResult(
            task_id=task_id,
            status=status,
            result=result,
            error=RuntimeError(result["text"]) if status == TaskStatus.FAILED else None,
            metadata={"outcome_unknown": result["state"] == "outcome_unknown", "retryable": False},
        )
