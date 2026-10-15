from datetime import UTC, datetime

import pytest
from agentbot_control.request_limits import RequestLimits
from agentbot_control.routines import RoutineDefinition, latest_due, next_time
from agentbot_control.schemas import Conflict
from control_support import _app as _app
from control_support import _create_bot as _create_bot
from control_support import _register as _register
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient


@pytest.mark.parametrize(
    "trigger,now,expected,upcoming",
    [
        (
            "interval",
            "2026-10-07T12:07:39+00:00",
            "2026-10-07T12:05:00+00:00",
            "2026-10-07T12:10:00+00:00",
        ),
        (
            "daily",
            "2026-11-01T06:45:00+00:00",
            "2026-11-01T05:30:00+00:00",
            "2026-11-02T06:30:00+00:00",
        ),
        (
            "daily",
            "2026-03-08T12:00:00+00:00",
            "2026-03-08T06:30:00+00:00",
            "2026-03-09T05:30:00+00:00",
        ),
    ],
)
def test_missed_occurrences_preserve_schedule_phase(trigger, now, expected, upcoming):
    definition = RoutineDefinition(
        name="Schedule",
        bot_id="bot",
        prompt="hello",
        trigger=trigger,
        interval_seconds=300,
        timezone="America/New_York",
        local_time="01:30",
    )
    original = datetime(2026, 1, 1, 12, tzinfo=UTC)
    due = latest_due(definition, original, datetime.fromisoformat(now))
    assert due.isoformat() == expected
    assert next_time(definition, due).isoformat() == upcoming


def test_routine_queue_is_bounded_and_retry_keeps_job_identity(tmp_path):
    app, _, _, _ = _app(tmp_path)
    with TestClient(app) as client:
        user = _register(client)
        bid = _create_bot(client).json()["id"]
        runtime = app.state.runtime
        runtime.accepting = False
        rid = client.post(
            f"/api/workspaces/personal_{user['id']}/routines",
            json={"name": "Queue", "bot_id": bid, "prompt": "hello"},
        ).json()["id"]
        routine = runtime.routines.get(user["id"], rid)
        first = runtime.routines.claim(routine, "manual:first")
        for index in range(63):
            runtime.routines.claim(routine, f"manual:{index}")
        assert runtime.routines.claim(routine, "manual:first")["id"] == first["id"]
        with pytest.raises(Conflict, match="queue limit"):
            runtime.routines.claim(routine, "manual:overflow")
        client.patch(
            f"/api/routines/{rid}",
            json={
                "version": 1,
                "enabled": False,
                "name": "Paused",
                "bot_id": bid,
                "prompt": "hello",
            },
        )
        client.portal.call(runtime.routines.dispatch, first)
        history = client.get(f"/api/routines/{rid}/history").json()
        assert next(job for job in history if job["id"] == first["id"])["state"] == "failed"
        assert not runtime.store.active(bid)


def test_read_cursors_are_monotonic_and_do_not_overwrite_profile(tmp_path):
    app, _, _, _ = _app(tmp_path)
    with TestClient(app) as client:
        _register(client)
        bid = _create_bot(client).json()["id"]
        preferences = client.get("/api/preferences").json()
        client.post("/api/preferences", json={**preferences, "display_role": "Reviewer"})
        with app.state.runtime.store.transaction() as db:
            app.state.runtime.store._event(db, bid, "test.read", {})
            app.state.runtime.store._event(db, bid, "test.read", {})
        first = client.post(f"/api/bots/{bid}/read-cursor", json={"sequence": 2})
        assert first.status_code == 200, first.text
        assert first.json()["display_role"] == "Reviewer"
        previous = client.post(f"/api/bots/{bid}/read-cursor", json={"sequence": 1})
        assert previous.json() == first.json()
        assert (
            client.post(f"/api/bots/{bid}/read-cursor", json={"sequence": 1000}).status_code == 409
        )


def test_chunked_request_limit_before_body_processing():
    app = FastAPI()
    app.add_middleware(RequestLimits)
    processed = []

    @app.post("/body")
    async def body(request: Request):
        processed.append(await request.body())
        return {"ok": True}

    with TestClient(app) as client:
        response = client.post("/body", content=iter([b"a" * 524288, b"b" * 524289]))
        assert response.status_code == 413
        assert not processed


def test_features_can_be_disabled_without_losing_basic_bot_reads(tmp_path, monkeypatch):
    monkeypatch.setenv("CONTROL_WORKSPACE_FEATURES", "0")
    app, _, _, _ = _app(tmp_path)
    with TestClient(app) as client:
        _register(client)
        bid = _create_bot(client).json()["id"]
        snapshot = client.get(f"/api/bots/{bid}/snapshot")
        assert snapshot.status_code == 200
        assert not snapshot.json()["capabilities"]["remote_control"]
        assert client.get(f"/api/bots/{bid}/computer").status_code == 404
        assert client.get("/api/bots").status_code == 200


def test_copied_database_and_blobs_restore_ownership_and_credentials(tmp_path):
    import hashlib
    import shutil
    import sqlite3

    from workspace_services_support import create_computer, live_app

    original = tmp_path / "original"
    restored = tmp_path / "restored"
    original.mkdir()
    restored.mkdir()
    app, _ = live_app(original)
    raw = b"restored,complete\n1,2\n"
    with TestClient(app) as client:
        user = _register(client)
        bid = _create_bot(client).json()["id"]
        computer = create_computer(client, bid)
        blobs = app.state.runtime.files.blobs
        aid = blobs.reserve(
            bid,
            computer["id"],
            "/workspace/results.csv",
            hashlib.sha256(raw).hexdigest(),
            len(raw),
            "text/csv",
        )
        (blobs.directory / aid).write_bytes(raw)
        cookies = dict(client.cookies)
    with (
        sqlite3.connect(original / "control.sqlite") as source,
        sqlite3.connect(restored / "control.sqlite") as destination,
    ):
        source.backup(destination)
        assert destination.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert not destination.execute("PRAGMA foreign_key_check").fetchall()
    shutil.copytree(app.state.runtime.store.blobs, restored / app.state.runtime.store.blobs.name)
    replacement, _, _, _ = _app(restored)
    with TestClient(replacement) as client:
        client.cookies.update(cookies)
        assert client.get(f"/api/bots/{bid}/artifacts/{aid}/content").content == raw
        bot = replacement.state.runtime.workspaces.bot(user["id"], bid)
        assert (
            replacement.state.catalog.open_model_config(user["id"], bot).api_key
            == "sk-test-key-1234"
        )
        _register(client, "foreign")
        assert client.get(f"/api/bots/{bid}/artifacts/{aid}/content").status_code == 404


def test_group_routine_recovers_both_admission_journals_without_duplicate_runs(
    tmp_path,
):
    from agentbot_control.groups import GroupTask
    from automation_support import wait_job

    app, _, _, _ = _app(tmp_path)
    with TestClient(app) as client:
        user = _register(client)
        bid = _create_bot(client).json()["id"]
        wid = "personal_" + user["id"]
        group = client.post(
            f"/api/workspaces/{wid}/groups",
            json={"name": "One worker", "bot_ids": [bid]},
        ).json()
        rid = client.post(
            f"/api/workspaces/{wid}/routines",
            json={"name": "Group", "group_id": group["id"], "prompt": "@group hello"},
        ).json()["id"]
        runtime = app.state.runtime
        runtime.accepting = False
        job = runtime.routines.claim(runtime.routines.get(user["id"], rid), "manual:recovery")
        handoffs = runtime.groups.submit(
            user["id"],
            group["id"],
            GroupTask(request_id="routine_" + job["id"], task="@group hello"),
        )
        bot = runtime.workspaces.bot(user["id"], bid)
        runtime.store.admit(bot, user["id"], "handoff_" + handoffs[0]["id"], "hello", "handoff")
        cookies = dict(client.cookies)
    restored, _, _, _ = _app(tmp_path)
    with TestClient(restored) as client:
        client.cookies.update(cookies)
        assert wait_job(client, rid, {"failed"})["state"] == "failed"
        with restored.state.runtime.store.transaction() as db:
            assert db.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == 1
            assert db.execute("SELECT state FROM handoffs").fetchone()[0] == "failed"


def test_connector_network_failure_is_reported_as_unavailable(tmp_path, monkeypatch):
    import httpx

    app, _, _, _ = _app(tmp_path)
    original = httpx.AsyncClient

    def offline(request):
        raise httpx.ConnectError("network unavailable", request=request)

    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: original(transport=httpx.MockTransport(offline), **kwargs),
    )
    with TestClient(app) as client:
        _register(client)
        bid = _create_bot(client).json()["id"]
        response = client.post(
            f"/api/bots/{bid}/connections/github",
            json={"repository": "owner/repo", "token": "test-token"},
        )
        assert response.status_code == 200, response.text
        assert response.json()["status"] == "unavailable"
        cid = response.json()["id"]
        rotated = client.post(
            f"/api/bots/{bid}/connections/{cid}/rotate",
            json={"repository": "owner/repo", "token": "new-test-token"},
        )
        assert rotated.json()["status"] == "unavailable"


@pytest.mark.parametrize("operation", ["reset", "hibernate"])
def test_lifecycle_can_retire_a_lease_when_the_input_service_failed(
    tmp_path, monkeypatch, operation
):
    import asyncio

    from agentbot_control.lifecycle import LifecycleCommand
    from workspace_services_support import create_computer, live_app

    app, manager = live_app(tmp_path)
    with TestClient(app) as client:
        _register(client)
        bid = _create_bot(client).json()["id"]
        sid = create_computer(client, bid)["id"]
        lease = client.post(
            f"/api/bots/{bid}/sessions/{sid}/control/acquire",
            json={
                "request_id": "acquire_failure_test",
                "client_id": "failed_input_tab",
                "generation": 1,
            },
        )
        assert lease.status_code == 200, lease.text

        async def failed_input(*args):
            raise RuntimeError("input service stopped")

        monkeypatch.setattr(manager._cache[sid], "human_input", failed_input)

        async def command():
            return await asyncio.wait_for(
                app.state.runtime.lifecycle.command(
                    bid,
                    operation,
                    LifecycleCommand(request_id="retire_failed_input", generation=1),
                ),
                timeout=2,
            )

        result = client.portal.call(command)
        assert result["status"] == "completed", result
        assert app.state.runtime.control.state(bid)["lease"] is None


def test_failed_reset_exposes_failed_new_generation_and_does_not_repeat(tmp_path, monkeypatch):
    from workspace_services_support import create_computer, live_app

    app, manager = live_app(tmp_path)
    with TestClient(app) as client:
        _register(client)
        bid = _create_bot(client).json()["id"]
        create_computer(client, bid)

        async def failed_provision(sid):
            raise RuntimeError("host capacity unavailable")

        monkeypatch.setattr(manager, "get_or_create", failed_provision)
        command = {"request_id": "failed_reset_once", "generation": 1}
        response = client.post(f"/api/bots/{bid}/lifecycle/reset", json=command).json()
        assert response["status"] == "failed"
        assert response["failed_step"] == "provision_new_instance"
        assert response["computer"]["generation"] == 2
        assert response["computer"]["status"] == "failed"
        assert client.post(f"/api/bots/{bid}/lifecycle/reset", json=command).json() == response
