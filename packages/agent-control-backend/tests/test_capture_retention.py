import base64
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from agentbot_control.capture_retention import CapturePolicy
from control_support import _app as _app
from control_support import _create_bot as _create_bot
from control_support import _register as _register
from fastapi.testclient import TestClient
from pydantic import ValidationError


@pytest.fixture
def env(tmp_path):
    app, _, _, _ = _app(tmp_path)
    with TestClient(app) as client:
        user = _register(client)
        bid = _create_bot(client).json()["id"]
        store = app.state.runtime.store
        yield client, store, bid, f"personal_{user['id']}"


def image(store, bid, size=80):
    return store.record_capture(
        bid, None, base64.b64encode(b"\x89PNG" + b"x" * (size - 4)).decode()
    )


def policy(store, wid, **changes):
    # Direct configuration avoids racing the asynchronous worker in algorithm tests.
    with store.transaction() as db:
        db.execute(
            "UPDATE workspace_capture_retention SET "
            + ",".join(f"{key}=?" for key in changes)
            + " WHERE workspace_id=?",
            (*changes.values(), wid),
        )


def ids(store, bid):
    return [c["capture_id"] for c in store.snapshot(bid)["captures"]]


def test_count_newest_concurrent_and_workspace_isolation(env):
    client, store, bid, wid = env
    other = client.post("/api/workspaces", json={"name": "Other"}).json()["id"]
    second = _create_bot(client, name="Second").json()["id"]
    with store.transaction() as db:
        db.execute("UPDATE bot_streams SET workspace_id=? WHERE bot_id=?", (other, second))
    other_image = image(store, second)
    policy(store, wid, max_count=3, max_age_seconds=None)
    with ThreadPoolExecutor(max_workers=4) as pool:
        images = list(pool.map(lambda _: image(store, bid), range(12)))
    with store.transaction() as db:
        newest = [
            r[0]
            for r in db.execute(
                "SELECT id FROM capture_storage WHERE bot_id=? ORDER BY sequence DESC LIMIT 3",
                (bid,),
            )
        ]
    assert ids(store, bid) == newest
    assert ids(store, second) == [other_image["capture_id"]]
    assert len([r for r in images if r["retained"]]) == 12
    assert store.captures.settings(wid)["usage"]["pending_bytes"] == 0


def test_quota_threshold_incoming_and_hysteresis(env):
    _, store, bid, wid = env
    # Use small limits directly to exercise real files and byte accounting.
    policy(
        store,
        wid,
        max_bytes=1000,
        reserve_percent=25,
        cleanup_target_percent=50,
        max_age_seconds=None,
    )
    first = image(store, bid, 250)
    second = image(store, bid, 250)
    third = image(store, bid, 249)
    assert len(ids(store, bid)) == 3  # 749 bytes: don't clean down to 500 yet.
    fourth = image(store, bid, 1 + 4)  # 754 includes the incoming PNG.
    assert fourth["retained"]
    assert ids(store, bid) == [fourth["capture_id"], third["capture_id"]]
    assert store.captures.settings(wid)["usage"]["screenshot_bytes"] == 254
    assert store.captures.read(bid, first["capture_id"]) is None
    assert store.captures.read(bid, second["capture_id"]) is None


def test_exact_quota_trigger_and_gib_math(env):
    _, store, bid, wid = env
    policy(store, wid, max_bytes=1000, max_age_seconds=None)
    image(store, bid, 250)
    image(store, bid, 250)
    image(store, bid, 250)
    assert store.captures.settings(wid)["usage"]["screenshot_bytes"] == 500
    assert store.captures.thresholds(
        {"max_bytes": 1024**3, "reserve_percent": 25, "cleanup_target_percent": 50}
    ) == {"trigger_bytes": 805306368, "target_bytes": 536870912}


@pytest.mark.parametrize("seconds", [86400, 604800])
def test_age_exact_cutoff_hides_before_worker_and_survives_replay(env, seconds):
    client, store, bid, wid = env
    now = datetime(2026, 3, 8, 7, tzinfo=UTC)
    store.captures.clock = lambda: now
    policy(store, wid, max_age_seconds=seconds)
    capture = image(store, bid)
    now += timedelta(seconds=seconds - 1)
    assert ids(store, bid) == [capture["capture_id"]]
    now += timedelta(seconds=1)
    assert ids(store, bid) == []
    assert client.get(capture["url"]).status_code == 404
    assert any(e["type"] == "capture.available" for e in store.snapshot(bid)["events"])
    store.captures.sweep()
    assert not (store.blobs / capture["capture_id"]).exists()


def test_missing_file_latest_and_snapshot_reconcile(env):
    client, store, bid, _ = env
    earlier = image(store, bid)
    missing = image(store, bid)
    (store.blobs / missing["capture_id"]).unlink()
    latest = client.get(f"/api/bots/{bid}/captures/latest")
    assert latest.status_code == 200
    assert latest.json()["capture_id"] == earlier["capture_id"]
    assert client.get(missing["url"]).status_code == 404
    snap = store.snapshot(bid)
    assert snap["captures_revision"] > 2
    assert [c["capture_id"] for c in snap["captures"]] == [earlier["capture_id"]]
    assert max(e["seq"] for e in snap["events"]) == snap["snapshot_seq"]


def test_locked_delete_stays_charged_and_retries(env, monkeypatch):
    _, store, bid, wid = env
    first = image(store, bid, 200)
    policy(store, wid, max_count=1, max_age_seconds=None)
    original = Path.unlink

    def locked(path, *args, **kwargs):
        if path.name == first["capture_id"]:
            raise PermissionError("locked")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", locked)
    assert image(store, bid)["retained"] is False
    settings = store.captures.settings(wid)
    assert settings["usage"]["pending_bytes"] == 200
    assert settings["usage"]["screenshot_bytes"] == 200
    assert settings["last_error"]
    assert ids(store, bid) == []
    monkeypatch.setattr(Path, "unlink", original)
    store.captures.recover()  # Startup resets retry deadlines.
    assert store.captures.settings(wid)["usage"]["screenshot_bytes"] == 0
    assert image(store, bid)["retained"]


def test_artifacts_are_never_evicted_and_pending_quota_is_counted(env):
    _, store, bid, wid = env
    first = image(store, bid, 80)
    # Existing files occupy the shared ceiling, independently of screenshot policy.
    with store.transaction() as db:
        db.execute(
            "INSERT INTO file_blobs VALUES ('artifact',?,'session','/workspace/output','rev',200,'text/plain',?)",
            (bid, datetime.now(UTC).isoformat()),
        )
    store.blob_limit = 210
    assert image(store, bid, 80)["retained"] is False
    assert store.captures.read(bid, first["capture_id"]) is None
    assert store.captures.settings(wid)["usage"]["file_bytes"] == 200
    with store.transaction() as db:
        assert db.execute("SELECT id FROM file_blobs WHERE id='artifact'").fetchone()


def test_policy_api_preview_revision_permissions_and_persistence(env):
    client, store, bid, wid = env
    for _ in range(3):
        image(store, bid)
    url = f"/api/workspaces/{wid}/capture-retention"
    current = client.get(url).json()
    assert current["max_age_seconds"] == 604800
    command = {"revision": 1, "max_count": 1, "max_age_seconds": None}
    preview = client.post(url + "/preview", json=command)
    assert preview.status_code == 200, preview.text
    assert preview.json()["remove_count"] == 2
    assert len(ids(store, bid)) == 3
    saved = client.patch(url, json=command)
    assert saved.status_code == 200, saved.text
    assert saved.json()["revision"] == 2
    assert client.patch(url, json=command).status_code == 409
    assert client.patch(url, json={"revision": 2, "max_bytes": 1024**3}).status_code == 422
    store.captures.recover()
    assert client.get(url).json()["max_count"] == 1
    assert len(ids(store, bid)) == 1
    client.cookies.clear()
    _register(client, username="viewer")
    assert client.get(url).status_code == 404
    assert client.patch(url, json={"revision": 2, "max_count": 5}).status_code == 404


@pytest.mark.parametrize(
    "changes",
    [
        {"max_count": 0},
        {"max_count": True},
        {"max_count": None, "max_bytes": None, "max_age_seconds": None},
        {"max_bytes": 8 * 1024**2, "reserve_percent": 50},
        {"max_bytes": 1024},
        {"max_age_seconds": 0},
    ],
)
def test_invalid_policies(changes):
    with pytest.raises(ValidationError):
        CapturePolicy(revision=1, **changes)


def test_write_failure_and_orphans_recover_without_new_capture_deletion(env, monkeypatch):
    _, store, bid, wid = env
    original = Path.replace
    monkeypatch.setattr(Path, "replace", lambda *args: (_ for _ in ()).throw(OSError("disk")))
    assert image(store, bid)["retained"] is False
    monkeypatch.setattr(Path, "replace", original)
    orphan = store.blobs / ("capture_" + "a" * 32 + ".tmp")
    orphan.write_bytes(b"abandoned")
    retained = image(store, bid)
    store.captures.recover()
    assert not orphan.exists()
    assert store.captures.read(bid, retained["capture_id"])
    assert store.captures.settings(wid)["usage"]["pending_bytes"] == 0


def test_bot_cascade_keeps_deletion_work(env):
    _, store, bid, wid = env
    capture = image(store, bid)
    with store.transaction() as db:
        db.execute("DELETE FROM bots WHERE id=?", (bid,))
        assert (
            db.execute(
                "SELECT state FROM capture_storage WHERE id=?", (capture["capture_id"],)
            ).fetchone()[0]
            == "pending_delete"
        )
    store.captures.sweep()
    assert not (store.blobs / capture["capture_id"]).exists()
    assert store.captures.settings(wid)["usage"]["screenshot_bytes"] == 0


def test_older_history_cursor_and_longer_policy(env):
    client, store, bid, wid = env
    policy(store, wid, max_age_seconds=30 * 86400)
    now = datetime.now(UTC) - timedelta(days=10)
    store.captures.clock = lambda: now
    for _ in range(4):
        image(store, bid)
    now = datetime.now(UTC)
    store.prune()
    captures = store.snapshot(bid)["captures"]
    assert len(captures) == 4
    page = client.get(
        f"/api/bots/{bid}/captures?before_sequence={captures[1]['storage_sequence']}"
    ).json()
    assert [c["capture_id"] for c in page] == [c["capture_id"] for c in captures[2:]]


def test_count_runs_before_disk_trigger(env):
    _, store, bid, wid = env
    for _ in range(3):
        image(store, bid, 200)
    # Count leaves 600 bytes including the incoming image, below the 750 trigger.
    policy(store, wid, max_count=2, max_bytes=1000, max_age_seconds=None)
    new = image(store, bid, 400)
    assert new["retained"]
    assert len(ids(store, bid)) == 2
    assert store.captures.settings(wid)["usage"]["screenshot_bytes"] == 600


def test_control_can_release_after_expiry_but_rejects_stale_click(tmp_path):
    from workspace_services_support import create_computer, live_app

    app, manager = live_app(tmp_path)
    with TestClient(app) as client:
        user = _register(client)
        bid = _create_bot(client).json()["id"]
        sid = create_computer(client, bid)["id"]
        store = app.state.runtime.store
        base = f"/api/bots/{bid}/sessions/{sid}/control"
        lease = client.post(
            base + "/acquire",
            json={
                "request_id": "acquire_retention",
                "client_id": "retention_tab",
                "generation": 1,
                "surface": "browser",
            },
        ).json()
        cap = client.get(f"/api/bots/{bid}/captures/latest").json()
        policy(store, "personal_" + user["id"], max_age_seconds=3600)
        with store.transaction() as db:
            db.execute(
                "UPDATE capture_records SET created_at=? WHERE bot_id=?",
                ((datetime.now(UTC) - timedelta(hours=2)).isoformat(), bid),
            )
        query = f"lease_id={lease['id']}&client_id=retention_tab&fence={lease['fence']}"
        packet = {
            "lease_id": lease["id"],
            "client_id": "retention_tab",
            "fence": lease["fence"],
            "generation": 1,
            "surface_id": lease["surface_id"],
            "viewport_revision": lease["viewport_revision"],
            "sequence": 1,
            "capture_id": cap["capture_id"],
        }
        with client.websocket_connect(base + "/ws?" + query) as socket:
            socket.send_json({**packet, "input": {"kind": "down", "x": 0, "y": 0}})
            assert socket.receive_json()["status"] == "rejected"
            socket.send_json({**packet, "capture_id": "", "input": {"kind": "release"}})
            assert socket.receive_json()["status"] == "applied"
            assert manager._cache[sid].inputs[-1][1]["kind"] == "release"


def test_upgrade_backfills_sequence_and_preserves_capture_bytes(env, tmp_path):
    import sqlite3

    from agentbot_control.event_store import EventStore

    _, store, bid, wid = env
    captures = [image(store, bid), image(store, bid)]
    restored_path = tmp_path / "upgrade.sqlite"
    restored_blobs = restored_path.with_suffix(".blobs")
    restored_blobs.mkdir()
    with sqlite3.connect(restored_path) as old:
        with store.lock:
            store.db.backup(old)
        old.executescript("""
            DROP TRIGGER capture_policy_workspace;
            DROP TRIGGER capture_storage_insert;
            DROP TRIGGER capture_storage_delete;
            DROP TABLE workspace_capture_retention;
            DROP TABLE capture_storage;
            ALTER TABLE bot_streams DROP COLUMN captures_revision;
            DELETE FROM schema_migrations WHERE version='017_capture_retention.sql';
        """)
    for capture in captures:
        (restored_blobs / capture["capture_id"]).write_bytes(
            store.captures.read(bid, capture["capture_id"])
        )
    upgraded = EventStore(restored_path)
    try:
        upgraded.captures.recover()
        assert upgraded.captures.settings(wid)["max_age_seconds"] == 604800
        assert set(ids(upgraded, bid)) == {c["capture_id"] for c in captures}
        assert all(upgraded.captures.read(bid, c["capture_id"]) for c in captures)
        with upgraded.transaction() as db:
            assert not db.execute("PRAGMA foreign_key_check").fetchall()
    finally:
        upgraded.db.close()
