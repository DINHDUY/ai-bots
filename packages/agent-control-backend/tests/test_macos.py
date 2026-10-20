"""Portable backend/companion contract tests; no native UI or live model."""

import threading

import pytest
from agentbot_macos.actions import Permit
from agentbot_macos.protocol import Hello
from agentbot_tools.open_interface import OiAgentAdapter
from control_support import _app, _create_bot, _register
from fastapi.testclient import TestClient
from runtime_support import start, wait_state


def pair(client):
    issued = client.post("/api/macos-computers/enrollments", json={"request_id": "mac-enrollment"})
    assert issued.status_code == 200, issued.text
    data = {"code": issued.json()["code"], "name": "Test Mac"}
    result = client.post("/api/macos-agents/enroll", json=data)
    assert result.status_code == 200, result.text
    assert client.post("/api/macos-agents/enroll", json=data).status_code == 403
    return result.json()


def select(client, bot, device):
    data = {"request_id": "select-mac", "device_id": device["device_id"], "expected_revision": 0}
    result = client.post(f"/api/bots/{bot}/compute-config", json=data)
    assert result.status_code == 200, result.text
    assert client.post(f"/api/bots/{bot}/compute-config", json=data).json() == result.json()


def test_mac_owner_scope_and_no_fallback(tmp_path):
    app, docker, _, _ = _app(tmp_path)
    with TestClient(app) as client:
        _register(client)
        bot = _create_bot(client, framework="open_interface").json()["id"]
        assert start(client, bot).status_code == 409
        device = pair(client)
        select(client, bot, device)
        assert start(client, bot).status_code == 409
        assert docker.created == 0
        assert "token" not in client.get("/api/macos-computers").text
        client.post("/api/logout")
        _register(client, "other")
        assert client.get("/api/macos-computers").json() == {"computers": []}
        assert (
            client.post(
                f"/api/macos-computers/{device['device_id']}/revoke",
                json={"request_id": "other-revoke"},
            ).status_code
            == 404
        )
        assert client.get(f"/api/bots/{bot}/taskstars/missing").status_code == 404


@pytest.mark.parametrize("decision", ["approve", "deny", "unknown", "autopilot"])
def test_mac_taskstar_approval_receipts_and_disconnect(tmp_path, decision):
    app, docker, _, _ = _app(tmp_path)

    async def completion(_):
        return "fixture model response"

    app.state.runtime.kernel.registry.register_framework(
        "open_interface", lambda: OiAgentAdapter(completion=completion)
    )
    commands, executed, errors = [], [], []
    with TestClient(app) as client:
        _register(client)
        bot = _create_bot(client, framework="open_interface").json()["id"]
        device = pair(client)
        select(client, bot, device)
        hello = Hello(
            device_id=device["device_id"],
            epoch="test-epoch",
            console_session="user:1",
            name="Test Mac",
            revision=1,
            sharing=True,
            armed=True,
            ready=True,
            screen_recording=True,
            accessibility=True,
        )
        with client.websocket_connect(
            "/api/macos-agents/connect", headers={"Authorization": "Bearer " + device["token"]}
        ) as ws:
            ws.send_json(hello.model_dump())
            ws.send_json({"type": "status", "state": hello.model_dump()})
            assert ws.receive_json()["type"] == "heartbeat"

            def companion():
                proposals = 0
                try:
                    while True:
                        message = ws.receive_json()
                        if message.get("type") == "heartbeat":
                            continue
                        method, args = message["method"], message["arguments"]
                        commands.append(method)
                        if method == "observe":
                            result = {"observation_id": "observation-1"}
                        elif method == "planner":
                            if args["operation"] == "prompt":
                                result = {
                                    "role": "OIPlanner",
                                    "messages": [{"role": "user", "content": "fixture"}],
                                }
                            elif args["operation"] == "response":
                                result = (
                                    {
                                        "finished": True,
                                        "effect_observed": True,
                                        "text": "Observed text",
                                    }
                                    if proposals
                                    else {
                                        "action": {
                                            "function": "set_text",
                                            "observation_id": "observation-1",
                                            "window_id": "1",
                                            "control_id": "ax-1",
                                            "arguments": {"text": "hello"},
                                        }
                                    }
                                )
                                proposals += 1
                            else:
                                result = {"ok": True}
                        elif method == "execute":
                            permit = Permit.model_validate(args)
                            permit.verify(device["token"], hello)
                            executed.append(permit.action_id)
                            result = {
                                "ok": True,
                                "dispatched": True,
                                "effect_observed": True,
                                "outcome_unknown": False,
                                "code": "completed",
                                "text": "Observed text",
                            }
                            if decision == "unknown":
                                result.update(
                                    ok=False,
                                    effect_observed=False,
                                    outcome_unknown=True,
                                    text="Native result lost; do not replay",
                                )
                        else:
                            result = {"stopped": True}
                        ws.send_json({"id": message["id"], "result": result})
                        if method == "local_stop":
                            return
                except BaseException as exc:
                    errors.append(exc)

            thread = threading.Thread(target=companion, daemon=True)
            thread.start()
            if decision == "autopilot":
                assert (
                    client.post(
                        f"/api/bots/{bot}/autopilot",
                        json={"request_id": "autopilot", "enabled": True, "expected_revision": 0},
                    ).status_code
                    == 200
                )
            task = {
                "producer": "qualification",
                "task_id": "task-1",
                "device_id": device["device_id"],
                "task_description": "Write hello in the test editor",
                "task_data": {},
                "timeout": 90.0,
            }
            url = f"/api/bots/{bot}/taskstars"
            response = client.post(url, json=task)
            assert response.status_code == 200, response.text
            receipt = response.json()
            assert client.post(url, json=task).json()["run_id"] == receipt["run_id"]
            assert (
                client.post(url, json={**task, "task_description": "Changed goal"}).status_code
                == 409
            )
            if decision != "autopilot":
                pending = wait_state(client, bot, lambda s: bool(s["pending_approvals"]))
                assert not executed
                aid = pending["pending_approvals"][0]["id"]
                approved = client.post(
                    f"/api/bots/{bot}/approvals/{aid}/decision",
                    json={
                        "request_id": "decide-mac",
                        "revision": 1,
                        "decision": "deny" if decision == "deny" else "approve",
                    },
                )
                assert approved.status_code == 200, approved.text
            final = wait_state(
                client,
                bot,
                lambda s: s.get("run", {}).get("status") in {"completed", "failed", "interrupted"},
            )
            result = client.get(url + "/" + receipt["request_id"]).json()
            assert len(executed) == (0 if decision == "deny" else 1)
            assert result["state"] == (
                "outcome_unknown"
                if decision == "unknown"
                else "failed"
                if decision == "deny"
                else "completed"
            ), (result, final)
            assert result["retryable"] is False
            assert client.post(url, json=task).json() == result
            assert docker.created == 0
            if decision == "unknown":
                assert final["computer"]["status"] == "failed"
                assert start(client, bot, request="unsafe-retry").status_code == 409
            second = _create_bot(client, framework="open_interface", name="Second").json()["id"]
            select(client, second, device)
            conflict = client.post(
                f"/api/bots/{second}/lifecycle/create",
                json={"request_id": "second-connect", "generation": 0},
            )
            assert conflict.json()["status"] == "failed", conflict.text
            assert conflict.json()["computer"]["status"] == "closed"
            assert (
                conflict.json()["detail"]
                == "Another bot is connected to this Mac; disconnect it first"
            )
            closed = client.post(
                f"/api/bots/{bot}/computer/close", json={"request_id": "close-mac"}
            )
            assert closed.status_code in {200, 202}, closed.text
            thread.join(5)
            assert not thread.is_alive() and not errors, errors
            assert "local_stop" in commands and not docker.closed
