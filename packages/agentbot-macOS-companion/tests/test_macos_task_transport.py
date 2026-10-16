import json

import httpx
import pytest
from agentbot_macos.taskstar import TaskAssignment, TaskStarBridge


@pytest.mark.asyncio
async def test_producer_retries_retain_identity_after_lost_admission_response():
    submissions = []

    def handler(request):
        submissions.append(request.content)
        raise httpx.ReadError("Response lost after admission")

    async with httpx.AsyncClient(
        base_url="https://control.invalid", transport=httpx.MockTransport(handler)
    ) as client:
        bridge = TaskStarBridge(client, "bot-1", result_factory=lambda _, value: value)
        for _ in range(2):
            result = await bridge.assign_task_to_device("task-1", "mac-1", "Write a draft", {}, 30)
            assert result["state"] == "outcome_unknown" and result["retryable"] is False
    assert len(submissions) == 2 and submissions[0] == submissions[1]


@pytest.mark.asyncio
async def test_completed_task_receipt_survives_producer_reconnect():
    def handler(request):
        return httpx.Response(
            200,
            json={
                "task_id": "task-1",
                "request_id": TaskAssignment.model_validate(json.loads(request.content)).request_id,
                "run_id": "run-1",
                "state": "completed",
                "text": "Verified",
                "effect_observed": True,
                "retryable": False,
            },
        )

    async with httpx.AsyncClient(
        base_url="https://control.invalid", transport=httpx.MockTransport(handler)
    ) as client:
        bridge = TaskStarBridge(client, "bot-1", result_factory=lambda _, value: value)
        result = await bridge.assign_task_to_device("task-1", "mac-1", "Write a draft", {}, 30)
        assert result["state"] == "completed" and result["effect_observed"]


@pytest.mark.asyncio
async def test_lost_auth_after_admission_cannot_report_known_failure():
    def handler(request):
        if request.method == "POST":
            task = TaskAssignment.model_validate_json(request.content)
            return httpx.Response(
                200,
                json={
                    "task_id": task.task_id,
                    "request_id": task.request_id,
                    "run_id": "run-1",
                    "state": "running",
                    "text": "Admitted",
                    "effect_observed": False,
                    "retryable": False,
                },
            )
        return httpx.Response(401)

    async with httpx.AsyncClient(
        base_url="https://control.invalid", transport=httpx.MockTransport(handler)
    ) as client:
        bridge = TaskStarBridge(client, "bot-1", result_factory=lambda _, value: value)
        result = await bridge.assign_task_to_device("task-1", "mac-1", "Write a draft", {}, 30)
        assert result["state"] == "outcome_unknown" and result["run_id"] == "run-1"
        assert result["retryable"] is False
