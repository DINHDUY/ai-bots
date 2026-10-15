from concurrent.futures import ThreadPoolExecutor

import pytest
from agentbot_control.repositories.admission import AdmissionLimits
from control_support import _app as _app
from control_support import _create_bot as _create_bot
from control_support import _register as _register
from fastapi.testclient import TestClient
from runtime_support import start as start
from runtime_support import wait_state as wait_state


@pytest.mark.parametrize("limit", ["runs", "runs_per_owner", "computers", "computers_per_owner"])
def test_atomic_capacity_duplicate_receipts_and_release(tmp_path, limit):
    app, sandboxes, _, _ = _app(tmp_path)
    app.state.runtime.store.admission_limits = AdmissionLimits(**{limit: 1})
    with TestClient(app) as client:
        _register(client)
        bots = [_create_bot(client).json()["id"] for _ in range(2)]
        with ThreadPoolExecutor(2) as pool:
            responses = list(pool.map(lambda bot: start(client, bot), bots))
        assert sorted(r.status_code for r in responses) == [202, 429]
        winner = next(i for i, response in enumerate(responses) if response.status_code == 202)
        loser = 1 - winner
        rejected = responses[loser]
        assert rejected.json()["code"] == "capacity_limit"
        assert int(rejected.headers["Retry-After"]) > 0
        accepted = responses[winner].json()
        assert start(client, bots[winner]).json() == accepted
        state = wait_state(client, bots[winner], lambda s: bool(s["pending_approvals"]))
        assert sandboxes.created == 1
        stopped = client.post(
            f"/api/bots/{bots[winner]}/runs/{accepted['run_id']}/stop",
            json={"request_id": "stop-capacity-test"},
        )
        assert stopped.status_code == 202
        wait_state(client, bots[winner], lambda s: s["run"]["status"] == "cancelled")
        if limit.startswith("computers"):
            assert start(client, bots[loser]).status_code == 429
            closed = client.post(
                f"/api/bots/{bots[winner]}/computer/close",
                json={"request_id": "close-capacity-test", "session_id": state["computer"]["id"]},
            )
            assert closed.status_code == 200, closed.text
        assert start(client, bots[loser]).status_code == 202


def test_per_owner_capacity_does_not_block_another_owner(tmp_path):
    app, _, _, _ = _app(tmp_path)
    app.state.runtime.store.admission_limits = AdmissionLimits(runs_per_owner=1)
    with TestClient(app) as alice, TestClient(app) as bob:
        _register(alice, "alice")
        _register(bob, "bob")
        first = _create_bot(alice).json()["id"]
        second = _create_bot(bob).json()["id"]
        assert start(alice, first).status_code == 202
        assert start(bob, second).status_code == 202


@pytest.mark.parametrize("value", ["0", "-1", "unlimited"])
def test_invalid_capacity_configuration_fails_startup(monkeypatch, value):
    monkeypatch.setenv("CONTROL_MAX_RUNS", value)
    with pytest.raises(ValueError, match="CONTROL_MAX_RUNS must be a positive integer"):
        AdmissionLimits.from_environment()
