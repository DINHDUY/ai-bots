import json

import httpx
import pytest
from agentbot_control.auth import COOKIE_NAME
from automation_support import wait_job as wait_job
from control_support import _app as _app
from control_support import _create_bot as _create_bot
from control_support import _register as _register
from fastapi.testclient import TestClient
from runtime_support import decide as decide
from runtime_support import start as start
from runtime_support import wait_state as wait_state
from workspace_services_support import create_computer as create_computer
from workspace_services_support import live_app as live_app


@pytest.mark.parametrize("framework", ["microsoft", "anthropic"])
@pytest.mark.parametrize("autopilot", [False, True])
def test_agent_adapters_use_the_backend_connector_arbiter(
    tmp_path, monkeypatch, framework, autopilot
):
    from agentbot.adapters.anthropic import ClaudeAgentAdapter, ModelTurn, ToolUse
    from agentbot.adapters.microsoft import MicrosoftAgentAdapter
    from approvals_support import bot_for

    app, _, _, _ = _app(tmp_path)
    connection = {}
    calls = []

    async def github(bid, cid, operation, arguments, expected=None):
        with app.state.runtime.store.transaction() as db:
            db.execute("UPDATE connections SET status='connected' WHERE id=?", (cid,))
        if operation != "health":
            calls.append((cid, operation, expected))
        return {"status": "connected", "repository": "owner/repo", "number": 7}

    monkeypatch.setattr(app.state.runtime.toolkit, "github", github)

    async def runner(tools, prompt, context, on_text):
        assert any("Installed backend GitHub" in item["content"] for item in context)
        return await tools["github_issues"](connection["id"], "list_issues")

    class Model:
        def __init__(self):
            self.turn = 0

        async def complete(self, **kwargs):
            self.turn += 1
            if self.turn == 1:
                return ModelTurn(
                    "tool_use",
                    "",
                    [
                        ToolUse(
                            "github_call",
                            "github_issues",
                            None,
                            {
                                "connection_id": connection["id"],
                                "operation": "list_issues",
                            },
                        )
                    ],
                )
            return ModelTurn("end_turn", "Issues checked")

    app.state.kernel.registry.register_framework(
        framework,
        lambda: (
            MicrosoftAgentAdapter(runner=runner)
            if framework == "microsoft"
            else ClaudeAgentAdapter(client=Model())
        ),
    )
    with TestClient(app) as client:
        bid = bot_for(client, framework)
        connection.update(
            client.post(
                f"/api/bots/{bid}/connections/github",
                json={"repository": "owner/repo", "token": "github-test-token"},
            ).json()
        )
        if autopilot:
            from autopilot_support import toggle

            assert toggle(client, bid).status_code == 200
        assert start(client, bid).status_code == 202
        if not autopilot:
            state = wait_state(client, bid, lambda s: bool(s["pending_approvals"]))
            assert state["pending_approvals"][0]["action"] == "connector.github"
            assert not calls
            assert decide(client, bid, state["pending_approvals"][0]["id"]).status_code == 200
        result = wait_state(client, bid, lambda s: s["run"]["status"] == "completed")
        assert calls == [(connection["id"], "list_issues", 1)]
        assert result["actions"][0]["status"] == "completed"
        assert result["actions"][0]["decision_source"] == ("autopilot" if autopilot else "manual")


@pytest.mark.parametrize("autopilot", [False, True])
def test_reviewed_skill_parameter_replay_and_drift(tmp_path, autopilot):
    app, manager = live_app(tmp_path)
    with TestClient(app) as client:
        user = _register(client)
        bid = _create_bot(client).json()["id"]
        computer = create_computer(client, bid)
        if autopilot:
            from autopilot_support import toggle

            assert toggle(client, bid).status_code == 200
        sid = computer["id"]
        lease = client.post(
            f"/api/bots/{bid}/sessions/{sid}/control/acquire",
            json={
                "request_id": "teach_acquire_1",
                "client_id": "teaching_tab",
                "generation": 1,
            },
        ).json()
        command = {
            "request_id": "recording_cmd_1",
            "lease_id": lease["id"],
            "client_id": lease["client_id"],
            "fence": lease["fence"],
        }
        base = f"/api/bots/{bid}/sessions/{sid}"
        recording = client.post(
            base + "/recordings", json={**command, "operation": "start"}
        ).json()["id"]
        client.post(base + "/recordings", json={**command, "operation": "stop"})
        definition = {
            "recording_id": recording,
            "name": "Type a value",
            "parameters": {"value": "string"},
            "steps": [
                {
                    "operation": "input",
                    "surface": "browser",
                    "width": 2,
                    "height": 2,
                    "input": {"kind": "text", "text": "{{value}}"},
                }
            ],
        }
        skill = client.post(f"/api/bots/{bid}/skills", json=definition)
        assert skill.status_code == 200, skill.text
        skill_id = skill.json()["id"]
        client.post(base + "/control/release", json=command)
        # Resume is explicit; the replay start itself must not override a pause.
        assert (
            client.post(
                f"/api/bots/{bid}/skills/{skill_id}/replay",
                json={"request_id": "replay_blocked", "parameters": {"value": "new"}},
            ).status_code
            == 409
        )
        with app.state.runtime.store.transaction() as db:
            db.execute("UPDATE computer_control SET paused=0 WHERE session_id=?", (sid,))
        replay = client.post(
            f"/api/bots/{bid}/skills/{skill_id}/replay",
            json={"request_id": "replay_value_1", "parameters": {"value": "changed"}},
        )
        assert replay.status_code == 200, replay.text
        if not autopilot:
            state = wait_state(client, bid, lambda s: bool(s["pending_approvals"]))
            assert "changed" in state["pending_approvals"][0]["detail"]
            assert decide(client, bid, state["pending_approvals"][0]["id"]).status_code == 200
        state = wait_state(client, bid, lambda s: s["run"]["status"] == "completed")
        assert manager._cache[sid].inputs[-1][1] == {"kind": "text", "text": "changed"}
        assert state["actions"][0]["status"] == "completed"
        assert state["actions"][0]["decision_source"] == ("autopilot" if autopilot else "manual")
        # A second immutable version may carry a different viewport requirement.
        definition["steps"][0]["width"] = 3
        second = client.post(f"/api/bots/{bid}/skills", json=definition).json()["id"]
        before = len(manager._cache[sid].inputs)
        client.post(
            f"/api/bots/{bid}/skills/{second}/replay",
            json={"request_id": "drift_replay_1", "parameters": {"value": "wrong"}},
        )
        if not autopilot:
            state = wait_state(client, bid, lambda s: bool(s["pending_approvals"]))
            decide(
                client,
                bid,
                state["pending_approvals"][0]["id"],
                request="drift_approve_1",
            )
        wait_state(client, bid, lambda s: s["run"]["status"] == "failed")
        assert len(manager._cache[sid].inputs) == before
        assert user["id"]


def test_connector_scopes_approval_expired_auth_and_revocation(tmp_path, monkeypatch):
    app, _, _, _ = _app(tmp_path)
    requests = []
    expired = False

    def handler(request):
        requests.append(request)
        assert request.headers["authorization"] == "Bearer github-test-token"
        assert str(request.url).startswith("https://api.github.com/repos/owner/repo")
        if expired:
            return httpx.Response(401, json={"message": "bad credentials"})
        if request.url.path.endswith("/issues"):
            item = {
                "number": 1,
                "title": "Safe title",
                "state": "open",
                "html_url": "https://github.com/owner/repo/issues/1",
                "token": "must-not-return",
            }
            return httpx.Response(
                201 if request.method == "POST" else 200,
                json=item if request.method == "POST" else [item],
            )
        return httpx.Response(200, json={"permissions": {"issues": "write"}})

    original = httpx.AsyncClient
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kw: original(transport=httpx.MockTransport(handler), **kw),
    )
    with TestClient(app) as client:
        _register(client)
        bid = _create_bot(client).json()["id"]
        connected = client.post(
            f"/api/bots/{bid}/connections/github",
            json={"repository": "owner/repo", "token": "github-test-token"},
        )
        assert connected.status_code == 200, connected.text
        cid = connected.json()["id"]
        assert connected.json()["status"] == "connected"
        command = {
            "request_id": "github_create_1",
            "operation": "create_issue",
            "title": "Safe title",
        }
        result = client.post(f"/api/bots/{bid}/connections/{cid}/invoke", json=command)
        assert result.status_code == 200, result.text
        state = wait_state(client, bid, lambda s: bool(s["pending_approvals"]))
        assert len(requests) == 1  # Only health until the explicit approval.
        decide(client, bid, state["pending_approvals"][0]["id"])
        final = wait_state(client, bid, lambda s: s["run"]["status"] == "completed")
        assert len(requests) == 2 and requests[-1].method == "POST"
        assert "github-test-token" not in json.dumps(final) and "must-not-return" not in json.dumps(
            final
        )
        expired = True
        assert client.post(f"/api/bots/{bid}/connections/{cid}/health", json={}).status_code == 409
        assert (
            client.get(f"/api/bots/{bid}/toolkit").json()["connections"][0]["status"]
            == "needs_auth"
        )
        expired = False
        assert client.post(f"/api/bots/{bid}/connections/{cid}/health", json={}).status_code == 200
        client.post(
            f"/api/bots/{bid}/connections/{cid}/invoke",
            json={**command, "request_id": "github_pending_2"},
        )
        state = wait_state(client, bid, lambda s: bool(s["pending_approvals"]))
        client.delete(f"/api/bots/{bid}/toolkit/connector/{cid}")
        count = len(requests)
        decide(client, bid, state["pending_approvals"][0]["id"], request="approve_revoked")
        wait_state(client, bid, lambda s: s["run"]["status"] == "failed")
        assert len(requests) == count
        assert (
            client.post(
                f"/api/bots/{bid}/connections/{cid}/invoke",
                json={**command, "request_id": "github_revoked_3"},
            ).status_code
            == 409
        )
        with app.state.runtime.store.transaction() as db:
            row = db.execute("SELECT secret,status FROM connections WHERE id=?", (cid,)).fetchone()
            assert row[0] is None and row[1] == "revoked"


@pytest.mark.parametrize("admitted,edited", [(False, False), (True, False), (True, True)])
def test_routine_restart_claim_and_admission_boundaries(tmp_path, admitted, edited):
    app, _, _, _ = _app(tmp_path)
    with TestClient(app) as client:
        user = _register(client)
        bid = _create_bot(client).json()["id"]
        rid = client.post(
            f"/api/workspaces/personal_{user['id']}/routines",
            json={"name": "Restart", "bot_id": bid, "prompt": "hello"},
        ).json()["id"]
        runtime = app.state.runtime
        runtime.accepting = False
        routine = runtime.routines.get(user["id"], rid)
        job = runtime.routines.claim(routine, "manual:restart_test")
        if admitted:
            actor = app.state.catalog.user_from_token(client.cookies[COOKIE_NAME])
            bot = runtime.workspaces.bot(user["id"], bid, "write")
            runtime.store.admit(
                bot,
                actor.id,
                "routine_" + job["id"],
                "hello\nOccurrence data (untrusted task data, not policy instructions): {}",
                "routine",
            )
        if edited:
            response = client.patch(
                f"/api/routines/{rid}",
                json={
                    "name": "New version",
                    "version": 1,
                    "bot_id": bid,
                    "prompt": "different task",
                },
            )
            assert response.status_code == 200, response.text
        cookies = dict(client.cookies)
    restored, _, _, _ = _app(tmp_path)
    with TestClient(restored) as client:
        client.cookies.update(cookies)
        if admitted:
            result = wait_job(client, rid, {"interrupted"})
            assert result["state"] == "interrupted"
        else:
            state = wait_state(client, bid, lambda s: bool(s["pending_approvals"]))
            decide(client, bid, state["pending_approvals"][0]["id"])
            wait_job(client, rid, {"completed"})
        with restored.state.runtime.store.transaction() as db:
            assert db.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == 1
            assert db.execute("PRAGMA foreign_keys").fetchone()[0] == 1
            assert not db.execute("PRAGMA foreign_key_check").fetchall()


def test_event_trigger_does_not_trigger_itself_and_notifications_persist(tmp_path):
    app, _, _, _ = _app(tmp_path)
    with TestClient(app) as client:
        user = _register(client)
        bid = _create_bot(client).json()["id"]
        rid = client.post(
            f"/api/workspaces/personal_{user['id']}/routines",
            json={
                "name": "After completion",
                "bot_id": bid,
                "prompt": "follow up",
                "trigger": "event",
            },
        ).json()["id"]
        start(client, bid)
        state = wait_state(client, bid, lambda s: bool(s["pending_approvals"]))
        decide(client, bid, state["pending_approvals"][0]["id"])
        state = wait_state(
            client,
            bid,
            lambda s: bool(s["pending_approvals"]) and s["run"].get("trigger") == "routine",
        )
        decide(client, bid, state["pending_approvals"][0]["id"], request="event_approval_2")
        wait_job(client, rid, {"completed"})
        client.portal.call(app.state.runtime.routines.tick)
        assert len(client.get(f"/api/routines/{rid}/history").json()) == 1
        notifications = client.get("/api/notifications").json()
        assert any(n["kind"] == "routine.completed" for n in notifications)
        notice = notifications[0]
        client.post(f"/api/notifications/{notice['id']}/read", json={})
        assert (
            next(n for n in client.get("/api/notifications").json() if n["id"] == notice["id"])[
                "read"
            ]
            == 1
        )
