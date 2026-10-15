import asyncio
import time
from concurrent.futures import ThreadPoolExecutor

import pytest
from control_support import _app as _app
from control_support import _create_bot as _create_bot
from control_support import _register as _register
from fastapi.testclient import TestClient
from runtime_support import decide as decide
from runtime_support import setup as setup
from runtime_support import start as start
from runtime_support import wait_state as wait_state
from starlette.websockets import WebSocketDisconnect


def test_refresh_and_two_observers_recover_the_same_approval(tmp_path):
    app, sandboxes, _, _ = _app(tmp_path)
    with TestClient(app) as client:
        bot = setup(client)
        assert client.get("/api/capabilities").json()["protocol_version"] == 2
        empty = client.get(f"/api/bots/{bot}/snapshot").json()
        assert empty["computer"] is None and sandboxes.created == 0
        response = start(client, bot)
        assert response.status_code == 202
        state = wait_state(client, bot, lambda s: bool(s["pending_approvals"]))
        aid = state["pending_approvals"][0]["id"]
        with client.websocket_connect(f"/api/bots/{bot}/events/ws") as first:
            snap = first.receive_json()["data"]
            assert snap["run"]["id"] == response.json()["run_id"]
            assert snap["pending_approvals"][0]["id"] == aid
        assert (
            client.get(f"/api/bots/{bot}/snapshot").json()["run"]["status"] == "awaiting_approval"
        )
        with client.websocket_connect(
            f"/api/bots/{bot}/events/ws?after_seq={snap['snapshot_seq']}"
        ) as observer:
            assert observer.receive_json()["type"] == "ready"
            assert decide(client, bot, aid).status_code == 200
            events = []
            while not events or events[-1]["type"] != "run.finished":
                events.append(observer.receive_json())
            assert len({e["event_id"] for e in events}) == len(events)
            assert events[0]["seq"] == snap["snapshot_seq"] + 1
        done = wait_state(client, bot, lambda s: s["run"]["status"] == "completed")
        assert [m["content"] for m in done["messages"]] == ["echo hello", "yes"]
        assert len({m["id"] for m in done["messages"]}) == 2
        assert sandboxes.created == 1
        assert response.json()["session_id"] != bot


def test_idempotent_and_concurrent_start_and_decision(tmp_path):
    app, sandboxes, _, _ = _app(tmp_path)
    with TestClient(app) as client:
        bot = setup(client)
        with ThreadPoolExecutor(2) as pool:
            responses = list(pool.map(lambda _: start(client, bot), range(2)))
        assert [r.status_code for r in responses] == [202, 202]
        assert responses[0].json() == responses[1].json()
        assert start(client, bot, prompt="different").status_code == 409
        assert start(client, bot, request="second_request").status_code == 409
        state = wait_state(client, bot, lambda s: bool(s["pending_approvals"]))
        aid = state["pending_approvals"][0]["id"]
        answer = decide(client, bot, aid)
        assert answer.status_code == 200
        assert decide(client, bot, aid).json() == answer.json()
        assert decide(client, bot, aid, "different_decision_id").json() == answer.json()
        assert sandboxes.created == 1


def test_legacy_and_v2_share_admission_and_legacy_disconnect_stops(tmp_path):
    app, _, _, _ = _app(tmp_path)
    with TestClient(app) as client:
        bot = setup(client)
        with client.websocket_connect("/ws") as legacy:
            legacy.send_json({"action": "start", "bot_id": bot, "prompt": "legacy"})
            assert legacy.receive_json()["event"] == "session"
            assert legacy.receive_json()["event"] == "approval_required"
            assert start(client, bot).status_code == 409
        state = wait_state(client, bot, lambda s: s["run"]["status"] == "cancelled")
        assert state["pending_approvals"] == []
        assert start(client, bot).status_code == 202


def test_restart_expires_approvals_without_replaying_runs(tmp_path):
    app, _, sessions, _ = _app(tmp_path)
    with TestClient(app) as client:
        bot_id = setup(client)
        from agentbot_control.auth import COOKIE_NAME

        user = app.state.catalog.user_from_token(client.cookies.get(COOKIE_NAME))
        # Simulate durable state left by a terminated worker, without a live coroutine.
        bot = app.state.catalog.get_bot(user.id, bot_id)
        sessions.save(bot_id, [{"role": "user", "content": "historical message"}])
        app.state.runtime.ensure(bot)
        receipt, _ = app.state.runtime.store.admit(bot, user.id, "crashed_request", "do work")
        app.state.runtime.store.ready(bot_id, receipt["run_id"])
        app.state.runtime.approvals.register(
            bot_id,
            receipt["run_id"],
            {
                "event": "approval_required",
                "source": "test",
                "approval_id": "old",
                "action": "bash",
                "detail": "do work",
            },
            120,
        )
        cookie = dict(client.cookies)
    restored, sandboxes, _, _ = _app(tmp_path)
    with TestClient(restored) as client:
        client.cookies.update(cookie)
        state = client.get(f"/api/bots/{bot_id}/snapshot").json()
        assert state["run"]["status"] == "interrupted"
        assert state["pending_approvals"] == []
        assert state["messages"][0]["occurred_at"] is None
        assert state["messages"][0]["content"] == "historical message"
        assert sandboxes.created == 0
        assert decide(client, bot_id, "old").json()["status"] == "expired"
        assert start(client, bot_id).status_code == 409  # Unknown sandbox writer is quarantined.


def test_foreign_resources_and_revoked_subscription(tmp_path):
    app, _, _, _ = _app(tmp_path)
    with TestClient(app) as client:
        bot = setup(client)
        receipt = start(client, bot).json()
        state = wait_state(client, bot, lambda s: bool(s["pending_approvals"]))
        aid = state["pending_approvals"][0]["id"]
        alice = dict(client.cookies)
        client.cookies.clear()
        _register(client, "bea")
        assert client.get(f"/api/bots/{bot}/snapshot").status_code == 404
        assert client.get(f"/api/bots/{bot}/runs/{receipt['run_id']}").status_code == 404
        assert start(client, bot).status_code == 404
        assert decide(client, bot, aid).status_code == 404
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect(f"/api/bots/{bot}/events/ws"):
                pass
        client.cookies.update(alice)
        with client.websocket_connect(f"/api/bots/{bot}/events/ws") as socket:
            socket.receive_json()
            socket.receive_json()
            client.post("/api/logout")
            with pytest.raises(WebSocketDisconnect):
                socket.receive_json()


def test_retention_gap_snapshot_and_message_pagination(tmp_path):
    app, _, sessions, _ = _app(tmp_path)
    with TestClient(app) as client:
        bot_id = setup(client)
        sessions.save(bot_id, [{"role": "user", "content": str(i)} for i in range(250)])
        snap = client.get(f"/api/bots/{bot_id}/snapshot").json()
        assert len(snap["messages"]) == 200
        page = client.get(f"/api/bots/{bot_id}/messages?before={snap['messages_before']}").json()
        assert [m["content"] for m in page["messages"]] == [str(i) for i in range(50)]
        start(client, bot_id)
        wait_state(client, bot_id, lambda s: bool(s["pending_approvals"]))
        with app.state.runtime.store.transaction() as db:
            db.execute("UPDATE bot_events SET occurred_at='2000-01-01T00:00:00+00:00'")
        app.state.runtime.store.prune()
        assert client.get(f"/api/bots/{bot_id}/events?after_seq=0").json()["resync_required"]
        with client.websocket_connect(f"/api/bots/{bot_id}/events/ws?after_seq=0") as socket:
            assert socket.receive_json()["type"] == "snapshot"


def test_second_runtime_owner_is_rejected(tmp_path):
    first, _, _, _ = _app(tmp_path)
    second, _, _, _ = _app(tmp_path)
    with TestClient(first):
        with pytest.raises(RuntimeError, match="Another control runtime"):
            with TestClient(second):
                pass


def test_stop_waits_for_inflight_mutation(tmp_path):
    from fakes import FakeSandbox

    class SlowSandbox(FakeSandbox):
        async def run_bash(self, command):
            await asyncio.sleep(0.4)
            self.files["/workspace/done"] = "settled"
            return "done"

    class Adapter:
        async def initialize(self, sandbox, **kwargs):
            self.sandbox = sandbox

        async def execute_step(self, prompt):
            await self.sandbox.run_bash(prompt)
            yield {"event": "log", "type": "RESULT", "payload": "done"}

    app, sandboxes, _, _ = _app(tmp_path)
    app.state.kernel.registry.register_framework("slow", Adapter)

    async def create(sid):
        return sandboxes._cache.setdefault(sid, SlowSandbox())

    sandboxes.get_or_create = create
    with TestClient(app) as client:
        _register(client)
        bot = _create_bot(client, framework="slow").json()["id"]
        receipt = start(client, bot).json()
        wait_state(client, bot, lambda s: s["run"]["status"] == "running")
        time.sleep(0.05)
        stop = client.post(
            f"/api/bots/{bot}/runs/{receipt['run_id']}/stop",
            json={"request_id": "stop_request"},
        )
        assert stop.status_code == 202
        assert stop.json()["status"] == "stopping"
        assert start(client, bot, "blocked_request").status_code == 409
        wait_state(client, bot, lambda s: s["run"]["status"] == "cancelled")
        assert sandboxes._cache[receipt["session_id"]].files["/workspace/done"] == "settled"


def test_snapshot_secret_filtering_and_capture_access(tmp_path):
    app, _, _, _ = _app(tmp_path)
    with TestClient(app) as client:
        bot = setup(client)
        receipt = start(client, bot, prompt="do not echo sk-test-key-1234").json()
        assert start(client, bot, prompt="do not echo sk-test-key-1234").json() == receipt
        store = app.state.runtime.store
        store.record_frame(
            bot,
            receipt["run_id"],
            {
                "event": "artifact_written",
                "meta": {"path": "/workspace/azure.env", "preview": "SECRET=private"},
            },
        )
        import base64

        store.record_capture(
            bot, receipt["run_id"], base64.b64encode(b"\x89PNG\r\nfixture").decode()
        )
        snap = client.get(f"/api/bots/{bot}/snapshot")
        assert "SECRET=private" not in snap.text and "sk-test-key-1234" not in snap.text
        event = next(e for e in snap.json()["events"] if e["type"] == "capture.available")
        assert client.get(event["data"]["url"]).content.startswith(b"\x89PNG")
        client.cookies.clear()
        assert client.get(event["data"]["url"]).status_code == 401


def test_close_retry_cannot_remove_the_next_generation(tmp_path):
    app, sandboxes, _, _ = _app(tmp_path)
    with TestClient(app) as client:
        bot = setup(client)
        first = start(client, bot).json()
        wait_state(client, bot, lambda s: bool(s["pending_approvals"]))
        body = {"request_id": "close_first_computer", "session_id": first["session_id"]}
        closed = client.post(f"/api/bots/{bot}/computer/close", json=body)
        assert closed.status_code == 200
        second = start(client, bot, "second_run_request").json()
        assert second["generation"] == first["generation"] + 1
        assert second["session_id"] != first["session_id"]
        assert client.post(f"/api/bots/{bot}/computer/close", json=body).json() == closed.json()
        assert second["session_id"] not in sandboxes.closed


@pytest.mark.docker
def test_control_stop_confirms_docker_process_exit(tmp_path):
    from agentbot.sandbox.docker import DockerSessionManager

    class ShellAdapter:
        async def initialize(self, sandbox, **kwargs):
            self.sandbox = sandbox

        async def execute_step(self, prompt):
            await self.sandbox.run_bash("touch /workspace/started; sleep 3; touch /workspace/late")
            yield {"event": "log", "type": "RESULT", "payload": "done"}

    app, _, _, _ = _app(tmp_path)
    manager = DockerSessionManager()
    manager.configure_scope("control", app.state.runtime.store.deployment)
    app.state.kernel.sandboxes = manager
    app.state.kernel.registry.register_framework("shell", ShellAdapter)
    with TestClient(app) as client:
        _register(client)
        bot = _create_bot(client, framework="shell").json()["id"]
        receipt = start(client, bot).json()
        try:
            wait_state(client, bot, lambda s: s["run"]["status"] == "running")
            sandbox = manager._sessions[receipt["session_id"]]
            for _ in range(100):
                if client.portal.call(sandbox.workspace_kind, "started") == "file":
                    break
                time.sleep(0.02)
            else:
                pytest.fail("Shell did not start")
            assert (
                client.post(
                    f"/api/bots/{bot}/runs/{receipt['run_id']}/stop",
                    json={"request_id": "docker_stop"},
                ).status_code
                == 202
            )
            wait_state(client, bot, lambda s: s["run"]["status"] == "cancelled")
            time.sleep(3.1)
            assert client.portal.call(sandbox.workspace_kind, "late") == "missing"
        finally:
            response = client.post(
                f"/api/bots/{bot}/computer/close",
                json={
                    "request_id": "docker_close",
                    "session_id": receipt["session_id"],
                },
            )
            assert response.status_code == 200
