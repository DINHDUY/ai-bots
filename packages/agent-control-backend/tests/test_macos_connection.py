"""Mac connection rejection, durable retries and conservative recovery; no native input."""

from contextlib import contextmanager

import pytest
from agentbot_control.macos import provider
from agentbot_control.schemas import Conflict
from agentbot_macos.protocol import Hello
from control_support import _app, _create_bot, _register
from fastapi.testclient import TestClient
from test_macos import pair, select


@contextmanager
def connected(client, device, **state):
    hello = Hello(
        device_id=device["device_id"],
        epoch="test-epoch",
        console_session="user:1",
        name="Test Mac",
        revision=1,
        **{
            "ready": True,
            "sharing": True,
            "armed": False,
            "screen_recording": True,
            "accessibility": True,
            **state,
        },
    )
    with client.websocket_connect(
        "/api/macos-agents/connect", headers={"Authorization": "Bearer " + device["token"]}
    ) as ws:
        ws.send_json(hello.model_dump())
        ws.send_json({"type": "status", "state": hello.model_dump()})
        assert ws.receive_json()["type"] == "heartbeat"
        yield ws, hello


def create(client, bot, request="connect-mac", generation=0):
    response = client.post(
        f"/api/bots/{bot}/lifecycle/create",
        json={"request_id": request, "generation": generation},
    )
    assert response.status_code == 200, response.text
    return response.json()


def configured(client):
    _register(client)
    bot = _create_bot(client, framework="open_interface").json()["id"]
    device = pair(client)
    select(client, bot, device)
    return bot, device


def test_offline_connect_replays_rejection_until_explicit_new_request(tmp_path):
    app, docker, _, _ = _app(tmp_path)
    with TestClient(app) as client:
        bot, device = configured(client)
        rejected = create(client, bot)
        assert rejected["status"] == "failed"
        assert rejected["detail"] == "Mac companion is offline"
        assert rejected["computer"]["status"] == "closed"
        with connected(client, device):
            assert create(client, bot) == rejected
            assert not app.state.runtime.macos.bindings
            accepted = create(client, bot, "new-connect", generation=1)
            assert accepted["status"] == "completed"
            assert accepted["computer"]["status"] == "running"
            assert accepted["computer"]["generation"] == 2
            assert create(client, bot, "new-connect", generation=1) == accepted
            conn = app.state.runtime.macos.connections[device["device_id"]]
            assert not conn.pending
            assert not docker.created


@pytest.mark.parametrize(
    ("state", "detail"),
    [
        (
            {"ready": False, "accessibility": False, "reason": "Accessibility permission required"},
            "Accessibility permission required",
        ),
        (
            {
                "ready": False,
                "screen_recording": False,
                "reason": "Screen Recording permission required",
            },
            "Screen Recording permission required",
        ),
        (
            {"sharing": False, "reason": "Connected; enable control locally"},
            "Select a window and enable Share screen in the macOS companion",
        ),
    ],
)
def test_missing_consent_does_not_quarantine_and_legacy_failure_reports_device(
    tmp_path, state, detail
):
    app, docker, _, _ = _app(tmp_path)
    with TestClient(app) as client:
        bot, device = configured(client)
        with connected(client, device, **state):
            rejected = create(client, bot)
            assert rejected["status"] == "failed"
            assert rejected["detail"] == detail
            assert rejected["computer"]["status"] == "closed"
            assert not app.state.runtime.macos.bindings
            # An old version left this unused session failed. Inspection must
            # report the selected device even though no binding was ever claimed.
            app.state.runtime.store.set_computer(bot, rejected["computer"]["id"], "failed")
            report = client.get(f"/api/bots/{bot}/computer").json()
            assert report["computer"]["status"] == "failed"
            assert report["reason"] == detail
            assert report["name"] == "Test Mac"
            assert not report["compatible"] and not report["local_control"]
            assert not docker.created


def test_rejection_receipt_survives_backend_restart(tmp_path):
    app, _, _, _ = _app(tmp_path)
    with TestClient(app) as client:
        bot, _ = configured(client)
        rejected = create(client, bot)
    restored, _, _, _ = _app(tmp_path)
    with TestClient(restored) as client:
        assert (
            client.post("/api/login", json={"username": "ada", "password": "password1"}).status_code
            == 200
        )
        assert create(client, bot) == rejected
        assert client.get(f"/api/bots/{bot}/snapshot").json()["computer"]["status"] == "closed"


def test_failure_after_binding_claim_preserves_recovery(tmp_path, monkeypatch):
    def fail(*_):
        raise Conflict("Unexpected failure after binding")

    monkeypatch.setattr(provider, "MacSandbox", fail)
    app, _, _, _ = _app(tmp_path)
    with TestClient(app) as client:
        bot, device = configured(client)
        with connected(client, device):
            rejected = create(client, bot)
            assert rejected["computer"]["status"] == "failed"
            assert "inspect the computer" in rejected["detail"]
            assert app.state.runtime.macos.binding(rejected["computer"]["id"])["active"]


@pytest.mark.parametrize("offline", ["closed", "stale"])
def test_stale_or_closed_connection_cannot_report_old_ready_status(tmp_path, offline):
    app, _, _, _ = _app(tmp_path)
    with TestClient(app) as client:
        bot, device = configured(client)
        with connected(client, device, armed=True):
            assert create(client, bot)["status"] == "completed"
            conn = app.state.runtime.macos.connections[device["device_id"]]
            if offline == "closed":
                conn.disconnect()
            else:
                conn.last_seen -= 20
            report = client.get(f"/api/bots/{bot}/computer").json()
            assert report["reason"] == "Mac companion is offline"
            assert not report["compatible"] and not report["local_control"]
