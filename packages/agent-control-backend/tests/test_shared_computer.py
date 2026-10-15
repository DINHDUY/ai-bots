"""Workspace-owned computer shared by eligible bots."""

from agentbot_control.common import identifier, stamp
from agentbot_control.repositories.admission import AdmissionLimits
from control_support import _create_bot, _register
from fastapi.testclient import TestClient
from runtime_support import decide, start, wait_state
from workspace_services_support import live_app


def _workspace(client, bot):
    return client.get(f"/api/bots/{bot}/snapshot").json()["workspace_id"]


def _share(client, wid, revision=0, request_id="sharemode01"):
    response = client.put(
        f"/api/workspaces/{wid}/computer",
        json={
            "request_id": request_id,
            "expected_revision": revision,
            "mode": "shared",
            "provider": "docker",
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def _create_shared(client, wid, generation=0):
    response = client.post(
        f"/api/workspaces/{wid}/computer/lifecycle",
        json={"request_id": "sharecreate1", "operation": "create", "generation": generation},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "completed", body
    return body["computer"]


def _events(client, bot):
    return [event["type"] for event in client.get(f"/api/bots/{bot}/snapshot").json()["events"]]


def test_owner_revision_and_active_computers(tmp_path):
    app, _ = live_app(tmp_path)
    with TestClient(app) as owner, TestClient(app) as operator:
        _register(owner)
        bot = _create_bot(owner, name="Writer").json()["id"]
        wid = _workspace(owner, bot)
        _register(operator, "operator")
        assert (
            owner.post(
                f"/api/workspaces/{wid}/members",
                json={"username": "operator", "role": "operator"},
            ).status_code
            == 200
        )
        denied = operator.put(
            f"/api/workspaces/{wid}/computer",
            json={
                "request_id": "operatorput1",
                "expected_revision": 0,
                "mode": "shared",
                "provider": "docker",
            },
        )
        assert denied.status_code == 404
        assert start(owner, bot, "perbotstart1").status_code == 202
        blocked = owner.put(
            f"/api/workspaces/{wid}/computer",
            json={
                "request_id": "shareblocked1",
                "expected_revision": 0,
                "mode": "shared",
                "provider": "docker",
            },
        )
        assert blocked.status_code == 409 and blocked.json()["code"] == "computers_active"
        state = wait_state(owner, bot, lambda item: item["pending_approvals"])
        decide(owner, bot, state["pending_approvals"][0]["id"], "approve_close_1")
        wait_state(
            owner,
            bot,
            lambda item: (
                item["run"]["status"]
                not in {"preparing", "running", "awaiting_approval", "stopping"}
            ),
        )
        generation = owner.get(f"/api/bots/{bot}/snapshot").json()["computer"]["generation"]
        assert (
            owner.post(
                f"/api/bots/{bot}/lifecycle/close",
                json={"request_id": "closeperbot1", "generation": generation},
            ).status_code
            == 200
        )
        saved = _share(owner, wid)
        stale = owner.put(
            f"/api/workspaces/{wid}/computer",
            json={
                "request_id": "sharemode02",
                "expected_revision": 0,
                "mode": "per_bot",
                "provider": "docker",
            },
        )
        assert stale.status_code == 409
        assert saved["revision"] == 1 and saved["mode"] == "shared"


class _LockedAdapter:
    """Routes the one tool call through the session action lock."""

    def __init__(self) -> None:
        self.streamer = None

    async def initialize(
        self, sandbox, memory_context, state_streamer, instructions="", model=None
    ):
        self.streamer = state_streamer

    def execute_step(self, prompt):
        return self._run(prompt)

    async def _run(self, prompt):
        from agentbot.interfaces import ActionResult

        async def execute():
            return ActionResult(True, "ok")

        async for item in self.streamer.execute_action(
            "echo", "bash", {"command": prompt}, prompt, execute
        ):
            if isinstance(item, dict):
                yield item
            else:
                yield self.streamer.emit_log("echo", "RESULT", "yes" if item.ok else "no")


def test_two_bots_share_one_session_and_serialize_actions(tmp_path):
    app, manager = live_app(tmp_path)
    app.state.kernel.registry.register_framework("microsoft", lambda: _LockedAdapter())
    with TestClient(app) as client:
        _register(client)
        first = _create_bot(client, name="Alpha").json()["id"]
        second = _create_bot(client, name="Beta").json()["id"]
        wid = _workspace(client, first)
        _share(client, wid)
        computer = _create_shared(client, wid)
        assert computer["scope"] == "workspace"
        assert set(computer["attached_bot_ids"]) == {first, second}
        assert manager.created == 1
        denied = client.post(
            f"/api/bots/{first}/lifecycle/create",
            json={"request_id": "botcreate001", "generation": 0},
        )
        assert denied.status_code == 409 and denied.json()["code"] == "workspace_computer"
        accepted = start(client, first, "sharedrun001")
        assert accepted.status_code == 202
        other = start(client, second, "sharedrun002")
        assert other.status_code == 202
        assert accepted.json()["session_id"] == other.json()["session_id"] == computer["id"]
        state = wait_state(client, first, lambda item: item["pending_approvals"])
        busy = client.post(
            f"/api/workspaces/{wid}/computer/lifecycle",
            json={
                "request_id": "shareclose01",
                "operation": "close",
                "generation": computer["generation"],
            },
        )
        assert busy.status_code == 409 and busy.json()["code"] == "computer_busy"
        assert client.get(f"/api/bots/{second}/snapshot").json()["pending_approvals"] == []
        decide(client, first, state["pending_approvals"][0]["id"], "approvealpha1")
        second_state = wait_state(client, second, lambda item: item["pending_approvals"])
        decide(client, second, second_state["pending_approvals"][0]["id"], "approvebeta01")
        wait_state(
            client,
            second,
            lambda item: not item["pending_approvals"] and item["run"]["status"] == "completed",
        )
        for bot in (first, second):
            snapshot = client.get(f"/api/bots/{bot}/snapshot").json()
            assert snapshot["computer"]["id"] == computer["id"]
            assert snapshot["computer"]["scope"] == "workspace"
            assert "session.running" in _events(client, bot)
        assert manager.created == 1


def test_one_lease_pauses_every_attached_bot(tmp_path):
    app, _ = live_app(tmp_path)
    with TestClient(app) as client:
        _register(client)
        first = _create_bot(client, name="Alpha").json()["id"]
        second = _create_bot(client, name="Beta").json()["id"]
        wid = _workspace(client, first)
        _share(client, wid)
        computer = _create_shared(client, wid)
        lease = client.post(
            f"/api/bots/{first}/sessions/{computer['id']}/control/acquire",
            json={
                "request_id": "take_shared1",
                "client_id": "first_tab",
                "generation": computer["generation"],
                "surface": "browser",
            },
        )
        assert lease.status_code == 200, lease.text
        paused = start(client, second, "pausedrun001")
        assert paused.status_code == 409
        assert paused.json()["code"] == "human_control"


def test_event_fanout_capacity_recovery_and_exclusions(tmp_path):
    app, _ = live_app(tmp_path)
    app.state.kernel.registry.register_framework("ufo", lambda: None)
    with TestClient(app) as client:
        user = _register(client)
        first = _create_bot(client, name="Alpha").json()["id"]
        second = _create_bot(client, name="Beta").json()["id"]
        desktop = _create_bot(client, name="Desktop", framework="ufo").json()["id"]
        paired = _create_bot(client, name="Windows", framework="microsoft").json()["id"]
        wid = _workspace(client, first)
        _share(client, wid)
        computer = _create_shared(client, wid)
        store = app.state.runtime.store
        now = stamp()
        with store.transaction() as db:
            db.execute(
                "INSERT INTO paired_computers VALUES (?,?,?,?,?,NULL)",
                ("device_1", user["id"], "Office PC", "token-hash", now),
            )
            db.execute(
                "INSERT INTO bot_compute_config VALUES (?,?,1)",
                (paired, "device_1"),
            )
        view = client.get(f"/api/workspaces/{wid}/computer").json()
        assert set(view["attached_bot_ids"]) == {first, second}
        assert client.get(f"/api/bots/{desktop}/snapshot").json()["computer"] is None
        report = client.get(f"/api/bots/{first}/computer").json()
        assert report["workspace_computer"] is True
        assert report["display_name"] == "Shared workspace computer"
        assert report["capabilities"]["lifecycle"] is False
        store.admission_limits = AdmissionLimits(computers_per_owner=1)
        team = client.post("/api/workspaces", json={"name": "Other"}).json()["id"]
        outsider = _create_bot(client, name="Outsider", workspace_id=team).json()["id"]
        limited = start(client, outsider, "capacityrun1")
        assert limited.status_code == 429 and limited.json()["code"] == "capacity_limit"
        with store.transaction() as db:
            count = db.execute(
                "SELECT COUNT(*) FROM computer_sessions WHERE status!='closed'"
            ).fetchone()[0]
        assert count == 1
        with store.transaction() as db:
            for bot in (first, second):
                db.execute(
                    "INSERT INTO runs (id,bot_id,session_id,user_id,status,prompt,config,trigger,created_at,updated_at) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (
                        identifier("run"),
                        bot,
                        computer["id"],
                        user["id"],
                        "preparing",
                        "recover",
                        "{}",
                        "user",
                        now,
                        now,
                    ),
                )
        recovered = store.recover()
        assert len(recovered) == 2
        failed = client.get(f"/api/bots/{first}/snapshot").json()["computer"]
        assert failed["status"] == "failed"
        assert client.get(f"/api/bots/{second}/snapshot").json()["computer"]["status"] == "failed"
        assert _events(client, first).count("session.failed") == 1
        assert "session.failed" in _events(client, second)


def test_per_bot_mode_is_unchanged(tmp_path):
    app, manager = live_app(tmp_path)
    with TestClient(app) as client:
        _register(client)
        first = _create_bot(client, name="Alpha").json()["id"]
        second = _create_bot(client, name="Beta").json()["id"]
        from workspace_services_support import create_computer

        own = create_computer(client, first)
        other = create_computer(client, second, request="create_computer_2")
        assert own["id"] != other["id"]
        assert manager.created == 2
        snapshot = client.get(f"/api/bots/{first}/snapshot").json()["computer"]
        assert snapshot["scope"] == "bot"
        assert snapshot["attached_bot_ids"] == [first]
