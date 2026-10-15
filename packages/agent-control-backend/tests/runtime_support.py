import time

import pytest
from control_support import _create_bot, _register


def wait_state(client, bot, predicate):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        state = client.get(f"/api/bots/{bot}/snapshot").json()
        if predicate(state):
            return state
        time.sleep(0.01)
    pytest.fail(f"State did not settle: {state}")


def start(client, bot, request="request_start_1", prompt="echo hello"):
    return client.post(f"/api/bots/{bot}/runs", json={"request_id": request, "prompt": prompt})


def decide(client, bot, approval, request="request_decide_1"):
    return client.post(
        f"/api/bots/{bot}/approvals/{approval}/decision",
        json={"request_id": request, "decision": "approve", "revision": 1},
    )


def setup(client):
    _register(client)
    return _create_bot(client).json()["id"]
