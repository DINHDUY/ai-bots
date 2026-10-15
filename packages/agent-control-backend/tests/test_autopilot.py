"""Autopilot exercises the same admission and dispatch path as manual approvals."""

import asyncio
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
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


def test_default_receipts_conflicts_and_origin(tmp_path):
    app, manager, _, _ = _app(tmp_path)
    with TestClient(app) as client:
        user = _register(client)
        bid = _create_bot(client).json()["id"]
        path = f"/api/bots/{bid}/autopilot"
        assert client.get("/api/capabilities").json()["autopilot"]
        initial = client.get(path).json()
        assert initial == {
            "bot_id": bid,
            "enabled": False,
            "revision": 0,
            "changed_by": None,
            "changed_at": None,
            "can_manage": True,
        }
        assert toggle(client, bid, False).json()["revision"] == 0
        with ThreadPoolExecutor(2) as pool:
            responses = list(
                pool.map(lambda _: toggle(client, bid, request="same_command"), range(2))
            )
        assert all(r.status_code == 200 for r in responses)
        assert responses[0].json() == responses[1].json()
        assert responses[0].json()["changed_by"] == user["id"]
        assert toggle(client, bid, True, 1).json()["revision"] == 1
        assert toggle(client, bid, False, 0).status_code == 409
        assert toggle(client, bid, False, 1, "same_command").status_code == 409
        assert (
            client.post(
                path,
                headers={"Origin": "https://untrusted.test"},
                json={
                    "request_id": "bad_origin",
                    "enabled": False,
                    "expected_revision": 1,
                },
            ).status_code
            == 403
        )
        assert (
            client.post(
                path,
                json={
                    "request_id": "invalid_bool",
                    "enabled": "false",
                    "expected_revision": 1,
                },
            ).status_code
            == 422
        )
        snapshot = client.get(f"/api/bots/{bid}/snapshot").json()
        assert snapshot["autopilot"]["enabled"] and manager.created == 0
        assert len([e for e in snapshot["events"] if e["type"] == "bot.autopilot.changed"]) == 1
        assert toggle(client, bid, False, 1).json()["revision"] == 2


def test_members_can_read_but_only_bot_owner_can_change(tmp_path):
    app, _, _, _ = _app(tmp_path)
    with TestClient(app) as owner, TestClient(app) as member:
        _register(owner)
        _register(member, "operator")
        wid = owner.post("/api/workspaces", json={"name": "Team"}).json()["id"]
        bid = _create_bot(owner, workspace_id=wid).json()["id"]
        path = f"/api/bots/{bid}/autopilot"
        assert member.get(path).status_code == 404
        assert toggle(member, bid).status_code == 404
        assert toggle(owner, bid).status_code == 200
        for role in ("viewer", "operator"):
            owner.post(
                f"/api/workspaces/{wid}/members",
                json={"username": "operator", "role": role},
            )
            assert member.get(path).json()["enabled"]
            assert not member.get(path).json()["can_manage"]
            assert toggle(member, bid, False, 1).status_code == 403
            assert start(member, bid).status_code == 403
        owner.post(
            f"/api/bots/{bid}/execution-grants",
            json={"username": "operator", "enabled": True},
        )
        assert toggle(member, bid, False, 1).status_code == 403
        assert start(member, bid).status_code == 202
        assert finished(member, bid)["messages"][-1]["content"] == "yes"
        owner.post(
            f"/api/workspaces/{wid}/members",
            json={"username": "operator", "role": "remove"},
        )
        assert member.get(path).status_code == 404


@pytest.mark.parametrize("framework", ["microsoft", "anthropic"])
def test_pending_and_future_actions_without_an_observer(tmp_path, framework):
    app, manager, _ = application(tmp_path, framework)
    with TestClient(app) as client:
        bid = bot_for(client, framework)
        receipt = start(client, bid, prompt="first command").json()
        approval = pending(client, bid)
        response = toggle(client, bid)
        assert response.status_code == 200, response.text
        assert response.json()["resolved_approval_ids"] == [approval["id"]]
        state = finished(client, bid)
        sandbox = manager._cache[receipt["session_id"]]
        assert sandbox.commands == ["first command"]
        action = state["actions"][0]
        assert action["decision_source"] == "autopilot" and action["autopilot_revision"] == 1
        assert action["status"] == "completed"
        assert start(client, bid, "future_request", "second command").status_code == 202
        state = finished(client, bid)
        assert sandbox.commands == ["first command", "second command"]
        assert len([e for e in state["events"] if e["type"] == "approval.required"]) == 1
        assert (
            len(
                [
                    n
                    for n in client.get("/api/notifications").json()
                    if n["kind"] == "approval.required"
                ]
            )
            == 1
        )
        assert toggle(client, bid, False, 1).status_code == 200
        start(client, bid, "manual_again", "third command")
        approval = pending(client, bid)
        assert sandbox.commands == ["first command", "second command"]
        decide(client, bid, approval["id"])
        assert finished(client, bid)["actions"][-1]["decision_source"] == "manual"
        assert sandbox.commands[-1] == "third command"


@pytest.mark.parametrize("reenable", [False, True])
def test_disable_fences_authorized_action_before_dispatch(tmp_path, monkeypatch, reenable):
    app, manager, _ = application(tmp_path)
    reached, release = threading.Event(), threading.Event()
    original = ActionArbiter.dispatch_context

    async def context(self, *args):
        reached.set()
        while not release.is_set():
            await asyncio.sleep(0.005)
        return await original(self, *args)

    monkeypatch.setattr(ActionArbiter, "dispatch_context", context)
    with TestClient(app) as client:
        bid = bot_for(client)
        toggle(client, bid)
        receipt = start(client, bid).json()
        try:
            assert reached.wait(3)
            response = toggle(client, bid, False, 1).json()
            assert len(response["invalidated_approval_ids"]) == 1
            if reenable:
                assert toggle(client, bid, True, 2).json()["revision"] == 3
        finally:
            release.set()
        state = finished(client, bid)
        assert manager._cache[receipt["session_id"]].commands == []
        assert state["actions"][0]["status"] == "cancelled"
        assert state["actions"][0]["approval_status"] == "cancelled"
        assert not any(e["type"] == "action.started" for e in state["events"])


def test_disable_allows_executing_action_to_finish(tmp_path):
    app, manager, _ = application(tmp_path)
    reached, release = threading.Event(), threading.Event()
    with TestClient(app) as client:
        bid = bot_for(client)
        receipt = start(client, bid).json()
        pending(client, bid)
        sandbox = manager._cache[receipt["session_id"]]
        original = sandbox.run_command

        async def execute(command):
            reached.set()
            while not release.is_set():
                await asyncio.sleep(0.005)
            return await original(command)

        sandbox.run_command = execute
        toggle(client, bid)
        try:
            assert reached.wait(3)
            assert toggle(client, bid, False, 1).json()["invalidated_approval_ids"] == []
        finally:
            release.set()
        assert finished(client, bid)["actions"][0]["status"] == "completed"
        assert sandbox.commands == ["echo hello"]


@pytest.mark.parametrize("resolution", ["denied", "expired", "cancelled"])
def test_enable_does_not_revive_terminal_decisions(tmp_path, resolution):
    app, manager, _ = application(tmp_path)
    with TestClient(app) as client:
        bid = bot_for(client)
        receipt = start(client, bid).json()
        approval = pending(client, bid)
        if resolution == "denied":
            client.post(
                f"/api/bots/{bid}/approvals/{approval['id']}/decision",
                json={
                    "request_id": "deny_request",
                    "decision": "deny",
                    "revision": 1,
                },
            )
        elif resolution == "expired":
            with app.state.runtime.store.transaction() as db:
                db.execute(
                    "UPDATE approvals SET expires_at='2000-01-01' WHERE id=?",
                    (approval["id"],),
                )
        else:
            client.post(
                f"/api/bots/{bid}/runs/{receipt['run_id']}/stop",
                json={"request_id": "stop_request"},
            )
        toggle(client, bid)
        finished(client, bid)
        status = app.state.runtime.approvals.get(approval["id"])["status"]
        assert status in ({"cancelled", "expired"} if resolution == "cancelled" else {resolution})
        assert manager._cache[receipt["session_id"]].commands == []


def test_legacy_streamer_immediate_and_pending_decisions(tmp_path):
    app, _, _, _ = _app(tmp_path)
    with TestClient(app) as client:
        _register(client)
        bid = _create_bot(client).json()["id"]
        start(client, bid)
        pending(client, bid)
        toggle(client, bid)
        assert finished(client, bid)["messages"][-1]["content"] == "yes"
        start(client, bid, "legacy_future")
        assert finished(client, bid)["messages"][-1]["content"] == "yes"
