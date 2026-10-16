"""Verify the pinned real TaskStar/HTTP bridge without native input or model calls."""

import asyncio
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


async def main():
    import httpx
    from agentbot_macos.taskstar import TaskAssignment, TaskStarBridge

    source = ROOT / "data/taskstar/source"
    manifest = json.loads((ROOT / "packages/agentbot-macOS-companion/upstream.json").read_text())
    for item in manifest["files"]:
        if item["kind"] == "ufo":
            assert (
                hashlib.sha256((source / item["path"]).read_bytes()).hexdigest()
                == item["patched_sha256"]
            )
    sys.path.insert(0, str(source))
    from galaxy.constellation.enums import TaskStatus
    from galaxy.constellation.task_star import TaskStar

    calls = []

    def handle(request):
        value = TaskAssignment.model_validate_json(request.content)
        calls.append(value)
        return httpx.Response(
            200,
            json={
                "task_id": value.task_id,
                "request_id": value.request_id,
                "run_id": "run-probe",
                "state": "completed",
                "text": "Scripted transport response",
                "effect_observed": True,
                "retryable": False,
            },
        )

    async with httpx.AsyncClient(
        base_url="https://control.invalid", transport=httpx.MockTransport(handle)
    ) as client:
        task = TaskStar(
            task_id="probe-task",
            description="Write a local test draft",
            target_device_id="mac-probe",
            task_data={"text": "Xin chào"},
            timeout=30,
        )
        result = await task.execute(TaskStarBridge(client, "bot-probe"))
        assert result.status == TaskStatus.COMPLETED and result.metadata["retryable"] is False
        assert len(calls) == 1 and calls[0].task_data == {"text": "Xin chào"}
        assert "Write a local test draft" in calls[0].task_description
        assert result.start_time and result.end_time
    print(
        "PASS: real pinned TaskStar.execute → TaskStarBridge → scripted HTTP result; no native/model qualification"
    )


if __name__ == "__main__":
    asyncio.run(main())
