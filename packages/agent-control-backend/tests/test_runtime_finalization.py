"""Stop must not cancel the cleanup that will publish a run's final state."""

import asyncio
import threading

import pytest
from agentbot.interfaces import TerminationUnverified
from control_support import _app, _create_bot, _register
from fakes import FakeSandbox
from fastapi.testclient import TestClient
from runtime_support import start, wait_state


@pytest.mark.parametrize("provider", ["docker", "macos_local", "windows_local"])
@pytest.mark.parametrize("result", ["completed", "failed", "unknown"])
def test_stop_during_finalization_settles_before_publishing(tmp_path, provider, result):
    entered = threading.Event()
    release = asyncio.Event()
    drains = []

    class Sandbox(FakeSandbox):
        async def cancel_commands(self):
            drains.append("started")
            entered.set()
            await release.wait()
            drains.append("settled")
            if result == "unknown":
                raise TerminationUnverified("Native result unverified")

    sandbox = Sandbox()
    sandbox.provider = provider

    class Adapter:
        async def initialize(self, **kwargs):
            pass

        async def execute_step(self, prompt):
            if result == "failed":
                raise RuntimeError("Observation failed before dispatch")
            yield {"event": "log", "type": "SYSTEM", "payload": "Finishing"}

    app, sandboxes, _, _ = _app(tmp_path)
    runtime = app.state.runtime
    runtime.kernel.registry.register_framework("finalization", Adapter)

    async def create(sid):
        return sandboxes._cache.setdefault(sid, sandbox)

    sandboxes.get_or_create = create
    with TestClient(app) as client:
        _register(client)
        bot = _create_bot(client, framework="finalization").json()["id"]
        receipt = start(client, bot).json()
        rid = receipt["run_id"]
        assert entered.wait(3), "Run never entered cleanup"
        try:
            for request in ("stop-during-cleanup", "stop-cleanup-again"):
                response = client.post(
                    f"/api/bots/{bot}/runs/{rid}/stop", json={"request_id": request}
                )
                assert response.status_code == 202
                assert response.json()["status"] == "stopping"
            assert start(client, bot, request="before-drain-settles").status_code == 409
            assert drains == ["started"]
            # Shutdown may cancel the owner again after an earlier user Stop.
            assert client.portal.call(lambda: runtime.tasks[rid].cancel())
        finally:
            client.portal.call(release.set)
        if result == "unknown" and provider == "docker":
            state = wait_state(client, bot, lambda s: s["computer"]["status"] == "failed")
            assert state["run"]["status"] == "stopping"
        else:
            expected = {"completed": "cancelled", "failed": "failed", "unknown": "interrupted"}[
                result
            ]
            state = wait_state(client, bot, lambda s: s["run"]["status"] == expected)
            assert rid not in runtime.tasks and rid not in runtime.guards
            events = client.get(f"/api/bots/{bot}/events?after_seq=0").json()["events"]
            finished = [e for e in events if e["type"] == "run.finished" and e["run_id"] == rid]
            assert len(finished) == 1
        assert drains == ["started", "settled"]
        if result == "unknown":
            assert state["computer"]["status"] == "failed"
            assert start(client, bot, request="unknown-must-stay-fenced").status_code == 409
        else:
            assert state["computer"]["status"] == "running"
            if result == "failed":
                assert state["run"]["outcome"] == "Observation failed before dispatch"
