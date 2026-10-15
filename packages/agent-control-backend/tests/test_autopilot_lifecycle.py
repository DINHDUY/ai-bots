"""Autopilot exercises the same admission and dispatch path as manual approvals."""

import uuid

import pytest
from approvals_support import application as application
from approvals_support import bot_for as bot_for
from approvals_support import finished as finished
from approvals_support import pending as pending
from approvals_support import save_rule as save_rule
from autopilot_support import toggle as toggle
from control_support import _app as _app
from control_support import _create_bot as _create_bot
from control_support import _register as _register
from fastapi.testclient import TestClient
from runtime_support import decide as decide
from runtime_support import start as start
from runtime_support import wait_state as wait_state
from workspace_services_support import create_computer as create_computer
from workspace_services_support import live_app as live_app


def test_mode_survives_restart_and_computer_lifecycle(tmp_path):
    app, _ = live_app(tmp_path)
    with TestClient(app) as client:
        _register(client)
        bid = _create_bot(client).json()["id"]
        toggle(client, bid)
        create_computer(client, bid)
        for operation, generation in [("hibernate", 1), ("resume", 1), ("reset", 1)]:
            response = client.post(
                f"/api/bots/{bid}/lifecycle/{operation}",
                json={
                    "request_id": uuid.uuid4().hex,
                    "generation": generation,
                },
            )
            assert response.status_code == 200, response.text
            assert response.json()["status"] == "completed", response.text
            assert client.get(f"/api/bots/{bid}/autopilot").json()["revision"] == 1
    restored, _, _, _ = _app(tmp_path)
    with TestClient(restored) as client:
        client.post("/api/login", json={"username": "ada", "password": "password1"})
        assert client.get(f"/api/bots/{bid}/autopilot").json()["enabled"]
        with restored.state.runtime.store.transaction() as db:
            assert db.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == 0
            assert not db.execute("PRAGMA foreign_key_check").fetchall()


def test_autopilot_does_not_resume_human_pause(tmp_path):
    app, _ = live_app(tmp_path)
    with TestClient(app) as client:
        _register(client)
        bid = _create_bot(client).json()["id"]
        computer = create_computer(client, bid)
        base = f"/api/bots/{bid}/sessions/{computer['id']}/control"
        assert (
            client.post(
                base + "/acquire",
                json={
                    "request_id": "human_control",
                    "client_id": "owner_tab",
                    "generation": 1,
                },
            ).status_code
            == 200
        )
        assert toggle(client, bid).status_code == 200
        assert client.get(base).json()["paused"]
        assert start(client, bid).status_code == 409


def test_group_handoffs_use_each_target_mode(tmp_path):
    app, _, _, _ = _app(tmp_path)
    with TestClient(app) as client:
        user = _register(client)
        bids = [_create_bot(client, name=name).json()["id"] for name in ("Auto", "Manual")]
        bids.sort()
        toggle(client, bids[0])
        group = client.post(
            f"/api/workspaces/personal_{user['id']}/groups",
            json={"name": "Pair", "bot_ids": bids},
        ).json()
        assert (
            client.post(
                f"/api/groups/{group['id']}/messages",
                json={
                    "request_id": "mixed_group",
                    "task": "@group say hello",
                    "budget": 2,
                },
            ).status_code
            == 200
        )
        first = wait_state(
            client,
            bids[0],
            lambda s: bool(s["run"]) and s["run"]["status"] == "completed",
        )
        assert first["actions"][0]["decision_source"] == "autopilot"
        approval = pending(client, bids[1])
        decide(client, bids[1], approval["id"])
        assert finished(client, bids[1])["actions"][0]["decision_source"] == "manual"


def test_routine_policy_override_and_normal_policy_after_disabling(tmp_path):
    from automation_support import wait_job

    app, _, _ = application(tmp_path)
    with TestClient(app) as client:
        bid = bot_for(client)
        uid = client.get("/api/me").json()["id"]
        start(client, bid)
        approval = pending(client, bid)
        rule = save_rule(client, bid, approval).json()
        decide(client, bid, approval["id"])
        finished(client, bid)
        toggle(client, bid)
        routine = client.post(
            f"/api/workspaces/personal_{uid}/routines",
            json={
                "name": "Autonomous",
                "bot_id": bid,
                "prompt": "hello",
                "approval_policy_id": "unavailable_policy",
            },
        )
        assert routine.status_code == 200, routine.text
        rid = routine.json()["id"]
        run = client.post(f"/api/routines/{rid}/run", json={"request_id": "routine_auto"})
        assert run.status_code == 200, run.text
        wait_job(client, rid, {"completed"})
        assert finished(client, bid)["actions"][-1]["decision_source"] == "autopilot"
        toggle(client, bid, False, 1)
        assert (
            client.post(f"/api/routines/{rid}/run", json={"request_id": "routine_off"}).status_code
            == 200
        )
        wait_job(client, rid, {"failed"})
        start(client, bid, "saved_rule_again")
        state = finished(client, bid)
        assert state["actions"][-1]["decision_source"] == "policy"
        assert rule["id"]


def test_autopilot_rechecks_changed_workspace_before_execution(tmp_path):
    app, manager, _ = application(tmp_path)
    with TestClient(app) as client:
        bid = bot_for(client)
        receipt = start(client, bid, prompt="python report.py").json()
        pending(client, bid)
        sandbox = manager._cache[receipt["session_id"]]
        sandbox.files["/workspace/report.py"] = "changed while waiting"
        toggle(client, bid)
        state = finished(client, bid)
        assert state["actions"][0]["status"] == "cancelled"
        assert not sandbox.commands


@pytest.mark.docker
def test_real_sandbox_autopilot_write_then_manual_gate(tmp_path):
    from agentbot.sandbox.docker import DockerSessionManager

    docker = pytest.importorskip("docker")
    app, _, _ = application(tmp_path)
    manager = DockerSessionManager(client=docker.from_env())
    manager.configure_scope("control", app.state.runtime.store.deployment)
    app.state.kernel.sandboxes = manager
    with TestClient(app) as client:
        bid = bot_for(client)
        toggle(client, bid)
        create_computer(client, bid)
        receipt = start(
            client, bid, prompt="printf autopilot > /workspace/autopilot-proof.txt"
        ).json()
        sid = receipt["session_id"]
        try:
            state = wait_state(
                client,
                bid,
                lambda s: bool(s["actions"]) and s["actions"][-1]["status"] == "completed",
            )
            finished(client, bid)
            assert state["actions"][0]["decision_source"] == "autopilot"
            sandbox = client.portal.call(manager.existing, sid)
            assert "autopilot" in client.portal.call(
                sandbox.read_workspace_file, "/workspace/autopilot-proof.txt"
            )
            toggle(client, bid, False, 1)
            start(
                client,
                bid,
                "docker_manual",
                "printf manual > /workspace/autopilot-proof.txt",
            )
            approval = pending(client, bid)
            assert "autopilot" in client.portal.call(
                sandbox.read_workspace_file, "/workspace/autopilot-proof.txt"
            )
            decide(client, bid, approval["id"])
            assert finished(client, bid)["actions"][-1]["status"] == "completed"
            assert "manual" in client.portal.call(
                sandbox.read_workspace_file, "/workspace/autopilot-proof.txt"
            )
        finally:
            client.post(
                f"/api/bots/{bid}/computer/close",
                json={"request_id": uuid.uuid4().hex, "session_id": sid},
            )


def test_restart_keeps_committed_mode_but_interrupts_unfinished_action(tmp_path):
    app, _, _, _ = _app(tmp_path)
    with TestClient(app) as client:
        user = _register(client)
        bid = _create_bot(client).json()["id"]
        toggle(client, bid)
        bot = app.state.catalog.get_bot(user["id"], bid)
        store = app.state.runtime.store
        receipt, _ = store.admit(bot, user["id"], "before_crash", "do work")
        store.ready(bid, receipt["run_id"])
        app.state.runtime.approvals.register(
            bid,
            receipt["run_id"],
            {
                "event": "approval_required",
                "source": "test",
                "approval_id": "crashed_approval",
                "action": "bash",
                "detail": "do work",
            },
            120,
        )
        assert app.state.runtime.approvals.get("crashed_approval")["decision_source"] == "autopilot"
    restored, manager, _, _ = _app(tmp_path)
    with TestClient(restored) as client:
        client.post("/api/login", json={"username": "ada", "password": "password1"})
        state = client.get(f"/api/bots/{bid}/snapshot").json()
        assert state["autopilot"]["enabled"] and state["autopilot"]["revision"] == 1
        assert state["run"]["status"] == "interrupted"
        assert state["actions"][0]["status"] == "cancelled"
        assert manager.created == 0
        assert not state["pending_approvals"]
        with restored.state.runtime.store.transaction() as db:
            assert db.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == 1
