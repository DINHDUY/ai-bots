"""Producer-side receipt polling. Transport uncertainty never creates another task."""

import asyncio
import time

import httpx

from agentbot_macos.results import TaskReceipt


async def submit(client: httpx.AsyncClient, route: str, assignment) -> dict:
    deadline = time.monotonic() + assignment.timeout
    result = {
        "task_id": assignment.task_id,
        "request_id": assignment.request_id,
        "run_id": "",
        "state": "running",
        "text": "",
        "effect_observed": False,
        "retryable": False,
    }

    def receipt(response):
        value = TaskReceipt.model_validate(response.json())
        if value.task_id != assignment.task_id or value.request_id != assignment.request_id:
            raise ValueError("Task receipt identity mismatch")
        return value.model_dump()

    try:
        async with asyncio.timeout(assignment.timeout):
            response = await client.post(route, json=assignment.model_dump())
            response.raise_for_status()
            result = receipt(response)
            while result["state"] == "running" and time.monotonic() < deadline:
                await asyncio.sleep(0.5)
                response = await client.get(route + "/" + assignment.request_id)
                response.raise_for_status()
                result = receipt(response)
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code < 500 and not result["run_id"]:
            return {
                **result,
                "state": "failed",
                "text": f"Task request rejected ({exc.response.status_code}); retain this task identity",
                "effect_observed": False,
            }
        result["state"] = "running"
    except (TimeoutError, httpx.TransportError, ValueError):
        result["state"] = "running"
    if result["state"] == "running":
        result.update(
            state="outcome_unknown",
            text="Producer transport or deadline ended; query the same task receipt before continuing",
            effect_observed=False,
        )
    return result
