import threading

import pytest
from agentbot_tools.ufo import UfoAgentAdapter
from agentbot_windows import UFO_REVISION
from agentbot_windows.execution import ActionNotDispatched
from agentbot_windows.protocol import Hello, Permit
from control_support import _app as _app
from control_support import _create_bot as _create_bot
from control_support import _register as _register
from fastapi.testclient import TestClient
from runtime_support import start as start
from runtime_support import wait_state as wait_state


def pair(client):
    code = client.post("/api/computers/enrollments", json={"request_id": "enrollment-request"})
    assert code.status_code == 200, code.text
    enrollment = {
        "request_id": "pairing-request",
        "code": code.json()["code"],
        "name": "Test Windows PC",
    }
    paired = client.post("/api/computer-agents/enroll", json=enrollment)
    assert paired.status_code == 200, paired.text
    assert client.post("/api/computer-agents/enroll", json=enrollment).status_code == 403
    return paired.json()


def select(client, bot, device):
    r = client.post(
        f"/api/bots/{bot}/compute-config",
        json={
            "request_id": "select-computer",
            "device_id": device["device_id"],
            "expected_revision": 0,
        },
    )
    assert r.status_code == 200, r.text


def test_pairing_owner_scope_and_no_docker_fallback(tmp_path):
    app, docker, _, _ = _app(tmp_path)
    with TestClient(app) as client:
        _register(client)
        bot = _create_bot(client, framework="ufo").json()["id"]
        assert start(client, bot).status_code == 409
        assert (
            client.post(
                f"/api/bots/{bot}/lifecycle/create",
                json={"request_id": "create-attempt", "generation": 0},
            ).status_code
            == 409
        )
        device = pair(client)
        select(client, bot, device)
        assert "token" not in client.get("/api/computers").text
        assert start(client, bot).status_code == 409
        assert docker.created == 0
        client.post("/api/logout")
        _register(client, "other")
        assert client.get("/api/computers").json() == {"computers": []}
        assert (
            client.post(
                f"/api/computers/{device['device_id']}/revoke",
                json={"request_id": "revoke-other"},
            ).status_code
            == 404
        )


def test_local_pause_before_worker_error_cancels_run_without_dispatch(tmp_path):
    app, docker, _, _ = _app(tmp_path)
    app.state.runtime.kernel.registry.register_framework("ufo", UfoAgentAdapter)
    commands, errors = [], []
    with TestClient(app) as client:
        _register(client)
        bot = _create_bot(client, framework="ufo").json()["id"]
        device = pair(client)
        select(client, bot, device)
        hello = Hello(
            epoch="test-epoch",
            windows_session="test:1",
            name="Test PC",
            revision=1,
            sharing=True,
            armed=True,
            ready=True,
            ufo_revision=UFO_REVISION,
        )
        with client.websocket_connect(
            "/api/computer-agents/connect",
            headers={"Authorization": "Bearer " + device["token"]},
        ) as ws:
            ws.send_json(hello.model_dump())
            ws.send_json({"type": "status", "state": hello.model_dump()})
            assert ws.receive_json()["type"] == "heartbeat"

            def companion():
                try:
                    while True:
                        request = ws.receive_json()
                        if request.get("type") == "heartbeat":
                            continue
                        method = request["method"]
                        commands.append(method)
                        if method == "planner":
                            stopped = hello.model_copy(
                                update={
                                    "revision": 2,
                                    "armed": False,
                                    "reason": "Physical mouse input; agent paused",
                                }
                            )
                            ws.send_json({"type": "status", "state": stopped.model_dump()})
                            ws.send_json(
                                {
                                    "id": request["id"],
                                    "error": "Windows worker stopped before dispatch: Physical mouse input; agent paused",
                                }
                            )
                        else:
                            ws.send_json({"id": request["id"], "result": {"stopped": True}})
                        if method == "local_stop":
                            return
                except BaseException as exc:
                    errors.append(exc)

            thread = threading.Thread(target=companion, daemon=True)
            thread.start()
            assert start(client, bot).status_code == 202
            result = wait_state(
                client, bot, lambda s: s.get("run", {}).get("status") == "cancelled"
            )
            assert result["computer"]["status"] == "running"
            assert app.state.runtime.control.state(bot)["paused"]
            assert start(client, bot, request="still-paused").status_code == 409
            assert "execute" not in commands and docker.created == 0
            assert client.post(
                f"/api/bots/{bot}/computer/close", json={"request_id": "close-paused"}
            ).status_code in {200, 202}
            thread.join(5)
            assert not thread.is_alive() and not errors, errors


@pytest.mark.parametrize(
    "decision",
    [
        "approve",
        "deny",
        "autopilot",
        "lost_result",
        "lost_result_with_pause",
        "preflight_rejected",
        "stale_replan",
        "literal_typing",
    ],
)
def test_ufo_run_uses_shared_dispatch_and_closes_only_binding(tmp_path, decision):
    app, docker, _, _ = _app(tmp_path)
    executed = []

    async def completion(_):
        return "fixture model response"

    app.state.runtime.kernel.registry.register_framework(
        "ufo", lambda: UfoAgentAdapter(completion=completion)
    )
    with TestClient(app) as client:
        _register(client)
        bot = _create_bot(client, framework="ufo").json()["id"]
        device = pair(client)
        select(client, bot, device)
        hello = Hello(
            epoch="test-epoch",
            windows_session="test:1",
            name="Test PC",
            revision=1,
            sharing=True,
            armed=True,
            ready=True,
            ufo_revision=UFO_REVISION,
        )
        with client.websocket_connect(
            "/api/computer-agents/connect",
            headers={"Authorization": "Bearer " + device["token"]},
        ) as ws:
            ws.send_json(hello.model_dump())
            ws.send_json({"type": "status", "state": hello.model_dump()})
            assert ws.receive_json()["type"] == "heartbeat"
            commands, errors = [], []

            def companion():
                responses = 0
                try:
                    while True:
                        request = ws.receive_json()
                        if request.get("type") == "heartbeat":
                            continue
                        method = request["method"]
                        commands.append(method)
                        args = request["arguments"]
                        if method == "observe":
                            result = {"observation_id": "observation-test"}
                        elif method == "planner":
                            op = args["operation"]
                            if op == "prompt":
                                result = {
                                    "role": "HostAgent",
                                    "messages": [{"role": "user", "content": "fixture"}],
                                }
                            elif op == "response":
                                result = (
                                    {"finished": True, "text": "fixture completed"}
                                    if responses >= (2 if decision == "stale_replan" else 1)
                                    else {
                                        "action": {
                                            "function": "type_text"
                                            if decision == "literal_typing"
                                            else "set_edit_text",
                                            "observation_id": f"observe-test-{responses}",
                                            "window_id": "1",
                                            "control_id": "2",
                                            "arguments": {"text": "hello"},
                                        },
                                        "application": "Test App",
                                    }
                                )
                                responses += 1
                            else:
                                result = {"ok": True}
                        elif method == "execute":
                            p = Permit.model_validate(args)
                            p.verify(device["token"], hello.epoch, hello.revision)
                            executed.append(p.action_id)
                            result = {
                                "ok": True,
                                "effect_observed": decision != "literal_typing",
                                "text": "Input dispatched; inspect the draft"
                                if decision == "literal_typing"
                                else "Text value verified",
                            }
                            if decision == "literal_typing":
                                assert p.action.function == "type_text"
                            if decision.startswith("lost_result"):
                                result = {
                                    "ok": False,
                                    "outcome_unknown": True,
                                    "text": "Response lost after dispatch; do not replay",
                                }
                                if decision == "lost_result_with_pause":
                                    paused = hello.model_copy(
                                        update={
                                            "armed": False,
                                            "revision": 2,
                                            "reason": result["text"],
                                        }
                                    )
                                    ws.send_json({"type": "status", "state": paused.model_dump()})
                            elif decision == "preflight_rejected":
                                result = ActionNotDispatched(
                                    "The target is read-only", "unsupported_text_control"
                                ).result()
                            elif decision == "stale_replan" and len(executed) == 1:
                                result = ActionNotDispatched(
                                    "stale_target: foreground changed", "stale_target"
                                ).result()
                        else:
                            result = {"stopped": True}
                        ws.send_json({"id": request["id"], "result": result})
                        if method == "local_stop":
                            return
                except BaseException as exc:
                    errors.append(exc)

            thread = threading.Thread(target=companion, daemon=True)
            thread.start()
            if decision in {"autopilot", "stale_replan"}:
                response = client.post(
                    f"/api/bots/{bot}/autopilot",
                    json={
                        "request_id": "enable-autopilot",
                        "enabled": True,
                        "expected_revision": 0,
                    },
                )
                assert response.status_code == 200, response.text
            admitted = start(client, bot)
            assert admitted.status_code == 202, admitted.text
            if decision not in {"autopilot", "stale_replan"}:
                pending = wait_state(client, bot, lambda s: bool(s["pending_approvals"]))
                assert not executed
                aid = pending["pending_approvals"][0]["id"]
                response = client.post(
                    f"/api/bots/{bot}/approvals/{aid}/decision",
                    json={
                        "request_id": "decide-windows",
                        "decision": "approve"
                        if decision.startswith("lost_result")
                        or decision in {"preflight_rejected", "literal_typing"}
                        else decision,
                        "revision": 1,
                    },
                )
                assert response.status_code == 200, response.text
            result = wait_state(
                client,
                bot,
                lambda s: (
                    s.get("run", {}).get("status") == "interrupted"
                    if decision.startswith("lost_result")
                    else s.get("run", {}).get("status") in {"completed", "failed"}
                ),
            )
            if decision.startswith("lost_result"):
                assert result["actions"][0]["result"]["outcome_unknown"]
                assert result["actions"][0]["status"] == "unknown"
                assert "Response lost after dispatch" in result["run"]["outcome"]
                assert result["computer"]["status"] == "failed"
                assert start(client, bot, request="do-not-replay").status_code == 409
            else:
                assert result["run"]["status"] == "completed", result
            assert len(executed) == (
                0 if decision == "deny" else 2 if decision == "stale_replan" else 1
            )
            if decision in {"preflight_rejected", "stale_replan"}:
                assert result["computer"]["status"] == "running"
                assert not app.state.runtime.control.state(bot)["paused"]
                rejected = next(item for item in result["actions"] if item["status"] == "failed")
                assert rejected["result"]["dispatched"] is False
                assert rejected["result"]["outcome_unknown"] is False
                if decision == "stale_replan":
                    assert len(set(executed)) == 2  # Fresh approval and claim, no replay.
                    assert {item["status"] for item in result["actions"]} == {"failed", "completed"}
            if (
                executed
                and not decision.startswith("lost_result")
                and decision not in {"preflight_rejected", "stale_replan"}
            ):
                assert result["actions"][0]["result"]["effect_observed"] is (
                    decision != "literal_typing"
                )
            assert docker.created == 0
            second = _create_bot(client, framework="ufo", name="Second bot").json()["id"]
            select(client, second, device)
            taken = client.post(
                f"/api/bots/{second}/lifecycle/create",
                json={"request_id": "second-connect", "generation": 0},
            )
            assert taken.json()["status"] == "failed", taken.text
            assert docker.created == 0
            closed = client.post(
                f"/api/bots/{bot}/computer/close", json={"request_id": "close-windows"}
            )
            # The canonical close endpoint is shared with the workspace.
            if closed.status_code == 404:
                closed = client.post(f"/api/bots/{bot}/close", json={"request_id": "close-windows"})
            assert closed.status_code in {200, 202}, closed.text
            thread.join(5)
            assert not errors and not thread.is_alive(), errors
            assert "local_stop" in commands and not docker.closed
