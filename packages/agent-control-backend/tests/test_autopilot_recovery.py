"""Autopilot exercises the same admission and dispatch path as manual approvals."""

import asyncio
import threading

from agentbot_control.approvals import ActionArbiter
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


def test_migration_preserves_existing_decisions_and_defaults_off(tmp_path):
    import sqlite3

    app, _, _ = application(tmp_path)
    with TestClient(app) as client:
        bid = bot_for(client)
        start(client, bid)
        approval = pending(client, bid)
        decide(client, bid, approval["id"])
        finished(client, bid)
    # Remove only the new schema from this private test database to exercise an upgrade.
    with sqlite3.connect(tmp_path / "control.sqlite") as db:
        db.execute("DROP TABLE bot_autopilot")
        db.execute("ALTER TABLE approvals DROP COLUMN decision_source")
        db.execute("ALTER TABLE approvals DROP COLUMN autopilot_revision")
        db.execute("DELETE FROM schema_migrations WHERE version='012_autopilot.sql'")
    restored, _, _, _ = _app(tmp_path)
    with TestClient(restored) as client:
        client.post("/api/login", json={"username": "ada", "password": "password1"})
        state = client.get(f"/api/bots/{bid}/snapshot").json()
        assert state["autopilot"]["revision"] == 0 and not state["autopilot"]["enabled"]
        assert state["actions"][0]["decision_source"] == "manual"
        assert state["actions"][0]["status"] == "completed"


def test_revoked_execution_grant_still_blocks_autopilot_dispatch(tmp_path, monkeypatch):
    app, manager, _ = application(tmp_path)
    reached, release = threading.Event(), threading.Event()
    original = ActionArbiter.dispatch_context

    async def context(self, *args):
        reached.set()
        while not release.is_set():
            await asyncio.sleep(0.005)
        return await original(self, *args)

    monkeypatch.setattr(ActionArbiter, "dispatch_context", context)
    with TestClient(app) as owner, TestClient(app) as member:
        bid = bot_for(owner)
        uid = owner.get("/api/me").json()["id"]
        _register(member, "operator")
        owner.post(
            f"/api/workspaces/personal_{uid}/members",
            json={"username": "operator", "role": "operator"},
        )
        owner.post(
            f"/api/bots/{bid}/execution-grants",
            json={"username": "operator", "enabled": True},
        )
        toggle(owner, bid)
        receipt = start(member, bid).json()
        try:
            assert reached.wait(3)
            owner.post(
                f"/api/bots/{bid}/execution-grants",
                json={"username": "operator", "enabled": False},
            )
        finally:
            release.set()
        assert finished(owner, bid)["actions"][0]["status"] == "failed"
        assert not manager._cache[receipt["session_id"]].commands


def test_disabling_during_routine_execution_keeps_its_actual_outcome(tmp_path):
    from automation_support import wait_job

    app, manager, _ = application(tmp_path)
    reached, release = threading.Event(), threading.Event()
    with TestClient(app) as client:
        bid = bot_for(client)
        uid = client.get("/api/me").json()["id"]
        computer = create_computer(client, bid)
        sandbox = manager._cache[computer["id"]]
        original = sandbox.run_command

        async def execute(command):
            reached.set()
            while not release.is_set():
                await asyncio.sleep(0.005)
            return await original(command)

        sandbox.run_command = execute
        toggle(client, bid)
        routine = client.post(
            f"/api/workspaces/personal_{uid}/routines",
            json={
                "name": "Already executing",
                "bot_id": bid,
                "prompt": "hello",
                "approval_policy_id": "expired_selected_policy",
            },
        ).json()
        rid = routine["id"]
        client.post(f"/api/routines/{rid}/run", json={"request_id": "running_routine"})
        try:
            assert reached.wait(3)
            toggle(client, bid, False, 1)
            client.portal.call(app.state.runtime.routines.tick)
            assert client.get(f"/api/routines/{rid}/history").json()[0]["state"] == "running"
        finally:
            release.set()
        wait_job(client, rid, {"completed"})
        assert finished(client, bid)["actions"][0]["status"] == "completed"
