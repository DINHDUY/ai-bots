"""Real process supervision, without importing native APIs or injecting input."""

import asyncio
import sys
import time

import pytest
from agentbot_macos.results import NotDispatched
from agentbot_macos.worker import Worker


@pytest.mark.asyncio
async def test_stop_kills_hung_process_and_fences_queued_calls(tmp_path):
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-c",
        "import time; time.sleep(60)",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
    )
    worker = Worker(tmp_path, tmp_path)
    worker.process = process
    first = asyncio.create_task(worker.call("observe", {}))
    queued = asyncio.create_task(worker.call("execute", {}))
    await asyncio.sleep(0.05)
    started = time.monotonic()
    await worker.stop()
    results = await asyncio.wait_for(asyncio.gather(first, queued, return_exceptions=True), 5)
    assert time.monotonic() - started < 3
    assert process.returncode is not None
    assert isinstance(results[0], asyncio.IncompleteReadError)
    assert isinstance(results[1], NotDispatched)
    assert worker.process is None
