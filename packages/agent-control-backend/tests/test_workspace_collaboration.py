import hashlib
import hmac
import time
from datetime import datetime

import pytest
from agentbot_control.routines import RoutineDefinition, next_time
from control_support import _app as _app
from control_support import _create_bot as _create_bot
from control_support import _register as _register
from fastapi.testclient import TestClient
from runtime_support import decide as decide
from runtime_support import start as start
from runtime_support import wait_state as wait_state
from workspace_services_support import LiveManager as LiveManager
from workspace_services_support import LiveSandbox as LiveSandbox
from workspace_services_support import create_computer as create_computer
from workspace_services_support import live_app as live_app
from workspace_services_support import png as png


def test_group_duplicate_dispatch_and_member_scope(tmp_path):
    app, _, _, _ = _app(tmp_path)
    with TestClient(app) as client:
        user = _register(client)
        wid = "personal_" + user["id"]
        bids = [_create_bot(client, name=name).json()["id"] for name in ("First", "Second")]
        group = client.post(
            f"/api/workspaces/{wid}/groups", json={"name": "Workers", "bot_ids": bids}
        ).json()
        command = {
            "request_id": "group_request_1",
            "task": "@group say hello",
            "budget": 2,
        }
        first = client.post(f"/api/groups/{group['id']}/messages", json=command)
        assert first.status_code == 200, first.text
        again = client.post(f"/api/groups/{group['id']}/messages", json=command).json()
        assert [r["id"] for r in first.json()] == [r["id"] for r in again]
        for bid in sorted(bids):
            state = wait_state(client, bid, lambda s: bool(s["pending_approvals"]))
            assert (
                decide(
                    client,
                    bid,
                    state["pending_approvals"][0]["id"],
                    request="approve_" + bid,
                ).status_code
                == 200
            )
        with app.state.runtime.store.transaction() as db:
            assert db.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == 2
        assert (
            client.post(
                f"/api/groups/{group['id']}/messages",
                json={**command, "task": "@group changed"},
            ).status_code
            == 409
        )


@pytest.mark.parametrize(
    "after,expected",
    [
        ("2026-03-08T06:00:00+00:00", "2026-03-09T06:30:00+00:00"),
        ("2026-11-01T04:00:00+00:00", "2026-11-01T05:30:00+00:00"),
        ("2026-11-01T05:31:00+00:00", "2026-11-02T06:30:00+00:00"),
    ],
)
def test_schedule_dst(after, expected):
    local = "02:30" if "03-08" in after else "01:30"
    definition = RoutineDefinition(
        name="daily",
        bot_id="bot",
        prompt="hello",
        trigger="daily",
        timezone="America/New_York",
        local_time=local,
    )
    assert next_time(definition, datetime.fromisoformat(after)).isoformat() == expected


def test_signed_webhook_dedup_and_routine_admission(tmp_path):
    app, _, _, _ = _app(tmp_path)
    with TestClient(app) as client:
        user = _register(client)
        bid = _create_bot(client).json()["id"]
        wid = "personal_" + user["id"]
        routine = client.post(
            f"/api/workspaces/{wid}/routines",
            json={
                "name": "Webhook task",
                "bot_id": bid,
                "prompt": "hello",
                "trigger": "webhook",
            },
        ).json()
        rid = routine["id"]
        secret = client.post(f"/api/routines/{rid}/webhook-secret", json={}).json()["secret"]
        raw = b'{"data":{"hello":"world"}}'
        timestamp = str(int(time.time()))
        delivery = "delivery_123"
        signature = hmac.new(
            secret.encode(),
            timestamp.encode() + b"." + delivery.encode() + b"." + raw,
            hashlib.sha256,
        ).hexdigest()
        headers = {
            "X-Agent-Timestamp": timestamp,
            "X-Agent-Delivery": delivery,
            "X-Agent-Signature": signature,
            "Content-Type": "application/json",
        }
        first = client.post(f"/api/webhooks/{rid}", content=raw, headers=headers)
        assert first.status_code == 200, first.text
        assert (
            client.post(f"/api/webhooks/{rid}", content=raw, headers=headers).json()["id"]
            == first.json()["id"]
        )
        assert (
            client.post(
                f"/api/webhooks/{rid}",
                content=raw,
                headers={**headers, "X-Agent-Signature": "bad"},
            ).status_code
            == 401
        )
        state = wait_state(client, bid, lambda s: bool(s["pending_approvals"]))
        assert decide(client, bid, state["pending_approvals"][0]["id"]).status_code == 200
        wait_state(client, bid, lambda s: s["run"]["status"] == "completed")
        with app.state.runtime.store.transaction() as db:
            assert db.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == 1
        assert len(client.get(f"/api/routines/{rid}/history").json()) == 1
        client.post(f"/api/routines/{rid}/webhook-secret", json={})
        assert client.post(f"/api/webhooks/{rid}", content=raw, headers=headers).status_code == 401
