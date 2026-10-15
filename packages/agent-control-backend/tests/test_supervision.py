import asyncio
import time

import pytest
from agentbot_control.supervision import PersistenceProbe, WorkerHealth
from control_support import _app as _app
from control_support import _create_bot as _create_bot
from control_support import _register as _register
from fastapi.testclient import TestClient


@pytest.mark.asyncio
async def test_progress_expiry_and_termination_fail_closed():
    now = [0.0]
    health = WorkerHealth(lambda: now[0])
    for name in (
        "run_cleanup",
        "computer_monitor",
        "control_leases",
        "routines",
        "channels",
        "capture_cleanup",
    ):
        health.start(name, asyncio.Event().wait(), timeout=10)
    assert health.admitting()
    assert not health.ready()
    for name in health.workers:
        health.progressed(name)
    assert health.ready()
    now[0] = 11
    assert not health.ready()
    assert not health.admitting()
    for name in health.workers:
        health.progressed(name)
    assert health.ready()
    for name, worker in health.workers.items():
        worker.task.cancel()
        await asyncio.gather(worker.task, return_exceptions=True)
        assert health.snapshot()[name] == "stopped"
        assert not health.admitting()
    await health.stop()


@pytest.mark.asyncio
async def test_optional_provider_failure_does_not_disable_other_bots():
    health = WorkerHealth()

    async def failed():
        raise RuntimeError("sensitive provider exception")

    task = health.start("cloud_reconciliation", failed(), timeout=10, required=False)
    await asyncio.gather(task, return_exceptions=True)
    assert health.ready()
    assert health.snapshot() == {"cloud_reconciliation": "stopped"}


@pytest.mark.parametrize(
    "name",
    [
        "run_cleanup",
        "computer_monitor",
        "control_leases",
        "routines",
        "channels",
        "capture_cleanup",
    ],
)
def test_dead_required_worker_changes_readiness_and_rejects_admission(tmp_path, monkeypatch, name):
    monkeypatch.setenv("SESSION_IDLE_SECONDS", "0.1")
    app, _, _, _ = _app(tmp_path)
    with TestClient(app) as client:
        _register(client)
        bot = _create_bot(client).json()["id"]
        deadline = time.monotonic() + 4
        while client.get("/ready").status_code != 200 and time.monotonic() < deadline:
            time.sleep(0.02)
        assert client.get("/ready").status_code == 200

        async def kill():
            task = app.state.runtime.store.health.workers[name].task
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

        client.portal.call(kill)
        assert client.get("/health").status_code == 200
        assert client.get("/ready").status_code == 503
        response = client.post(
            f"/api/bots/{bot}/runs", json={"request_id": "worker-failure-test", "prompt": "do work"}
        )
        assert response.status_code == 503
        assert response.json()["code"] == "worker_unavailable"


async def test_slow_readiness_probe_is_bounded_and_shared_until_it_settles():
    release = asyncio.Event()
    calls = 0

    async def slow_read():
        nonlocal calls
        calls += 1
        await release.wait()

    probe = PersistenceProbe(slow_read, timeout=0.01)
    try:
        # Database cancellation drains started work, so readiness must not use
        # wait_for to cancel that work or enqueue another probe on each poll.
        results = await asyncio.wait_for(asyncio.gather(*(probe.healthy() for _ in range(20))), 1)
        assert results == [False] * 20
        assert calls == 1
        assert probe.task is not None and not probe.task.cancelled()
        release.set()
        assert await probe.healthy()
    finally:
        release.set()
        await probe.close()


async def test_failed_persistence_probe_does_not_leak_exception_and_can_recover():
    failed = True

    async def read():
        if failed:
            raise OSError("test database unavailable")

    probe = PersistenceProbe(read)
    assert not await probe.healthy()
    failed = False
    assert await probe.healthy()
    await probe.close()
