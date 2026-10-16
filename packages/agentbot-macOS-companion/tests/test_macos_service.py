import time

import pytest
from agentbot_macos.results import NotDispatched
from agentbot_macos.service import Companion
from test_macos_protocol import hello, permit


class Worker:
    def __init__(self, result=None, error=None):
        self.calls = []
        self.result = result or {"ok": True, "dispatched": True}
        self.error = error

    async def call(self, method, args, check, deadline):
        check()
        self.calls.append((method, args))
        if self.error:
            raise self.error
        return self.result

    async def stop(self):
        pass


def companion(tmp_path, worker):
    c = Companion(
        {"device_id": "mac-test", "name": "Test Mac", "token": "test-secret"},
        None,
        None,
        tmp_path / "receipts.sqlite",
        session_check=lambda: {
            "ready": True,
            "screen_recording": True,
            "accessibility": True,
            "console_session": "501:1",
            "reason": "",
        },
        worker=worker,
    )
    c.epoch = hello().epoch
    c.state.change(sharing=True, armed=True)
    c.state.last_contact = time.monotonic()
    return c


@pytest.mark.asyncio
async def test_duplicate_execution_returns_receipt_without_native_input(tmp_path):
    worker = Worker()
    c = companion(tmp_path, worker)
    p = permit()
    assert (await c.execute(p.model_dump()))["ok"]
    assert (await c.execute(p.model_dump()))["ok"]
    assert len(worker.calls) == 1
    c.journal.close()


@pytest.mark.asyncio
async def test_dispatch_failure_fences_control_and_never_replays(tmp_path):
    worker = Worker(error=RuntimeError("worker lost"))
    c = companion(tmp_path, worker)
    p = permit()
    result = await c.execute(p.model_dump())
    assert result["outcome_unknown"] and not c.state.armed
    c.state.change(armed=True)
    p.local_revision = c.state.revision
    p.sign("test-secret")
    assert (await c.execute(p.model_dump()))["outcome_unknown"]
    assert len(worker.calls) == 1
    c.journal.close()


@pytest.mark.asyncio
async def test_local_stop_or_bad_permit_prevents_worker_call(tmp_path):
    worker = Worker()
    c = companion(tmp_path, worker)
    p = permit()
    await c.local_stop()
    assert not (await c.execute(p.model_dump()))["dispatched"]
    assert not worker.calls
    c.journal.close()


@pytest.mark.asyncio
async def test_preflight_rejection_is_known_not_dispatched(tmp_path):
    c = companion(
        tmp_path, Worker(error=NotDispatched("Changed before native dispatch", "stale_target"))
    )
    result = await c.execute(permit().model_dump())
    assert not result["dispatched"] and not result["outcome_unknown"]
    assert c.state.armed
    c.journal.close()
