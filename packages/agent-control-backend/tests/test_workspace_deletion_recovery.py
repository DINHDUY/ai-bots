"""Deletion survives response loss, cleanup faults, and process restart."""

from concurrent.futures import ThreadPoolExecutor

import pytest
from agentbot_control.common import stamp
from agentbot_control.schemas import Conflict
from control_support import _app, _create_bot, _register
from fastapi.testclient import TestClient
from workspace_delete_support import cleaned, deleted, deletion


def workspace_bot(client):
    wid = client.post("/api/workspaces", json={"name": "Delete me"}).json()["id"]
    bot = _create_bot(client, workspace_id=wid).json()
    return wid, bot["id"]


def test_failed_cleanup_retry_restart_and_concurrent_receipts(tmp_path, monkeypatch):
    app, _, _, _ = _app(tmp_path)
    with TestClient(app) as client:
        _register(client)
        wid, bid = workspace_bot(client)
        blobs = app.state.runtime.files.blobs
        blob = blobs.reserve(bid, "closed", "file.txt", "version", 7, "text/plain")
        (blobs.directory / blob).write_text("private", encoding="utf-8")
        remover = app.state.runtime.workspace_deletions.cleanup
        original = remover.remove

        def denied(kind, rid):
            if kind == "artifact":
                raise PermissionError("locked")
            original(kind, rid)

        monkeypatch.setattr(remover, "remove", denied)
        cmd = deletion(client, wid)
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(
                pool.map(
                    lambda _: client.post(f"/api/workspaces/{wid}/deletions", json=cmd), range(2)
                )
            )
        assert all(r.status_code in (200, 202) for r in results)
        failed = cleaned(client, state="needs_attention")
        assert failed["cleanup"]["bytes_remaining"] == 7
        assert (blobs.directory / blob).exists()
        assert client.get(f"/api/bots/{bid}/artifacts/{blob}").status_code == 404
    restored, _, _, _ = _app(tmp_path)
    with TestClient(restored) as client:
        assert (
            client.post("/api/login", json={"username": "ada", "password": "password1"}).status_code
            == 200
        )
        assert (
            client.post(
                f"/api/workspace-deletions/{cmd['request_id']}/retry-cleanup", json={}
            ).status_code
            == 200
        )
        cleaned(client)
        assert not (blobs.directory / blob).exists()
        assert client.post(f"/api/workspaces/{wid}/deletions", json=cmd).status_code == 200
        assert wid not in [w["id"] for w in client.get("/api/workspaces").json()]
        with restored.state.runtime.store.transaction() as db:
            assert not db.execute(
                "SELECT 1 FROM workspace_channels WHERE workspace_id=?", (wid,)
            ).fetchone()


@pytest.mark.parametrize(
    "record", ["writer", "run", "awaiting_approval", "stopping", "action", "computer", "lease"]
)
def test_blockers_leave_workspace_unchanged(tmp_path, record):
    app, _, _, _ = _app(tmp_path)
    with TestClient(app) as client:
        uid = _register(client)["id"]
        wid, bid = workspace_bot(client)
        cmd = deletion(client, wid)
        with app.state.runtime.store.transaction() as db:
            if record == "writer":
                db.execute(
                    "INSERT INTO workspace_file_writers(id,bot_id,created_at) VALUES ('transfer',?,?)",
                    (bid, stamp()),
                )
            elif record in ("run", "awaiting_approval", "stopping", "action"):
                db.execute(
                    "INSERT INTO runs(id,bot_id,user_id,status,prompt,config,trigger,created_at,updated_at) VALUES ('run',?,?,?,'private','{}','user',?,?)",
                    (
                        bid,
                        uid,
                        {"run": "running", "action": "completed"}.get(record, record),
                        stamp(),
                        stamp(),
                    ),
                )
                if record == "action":
                    db.execute(
                        "INSERT INTO actions(id,run_id,name,argument_digest,status) VALUES ('action','run','bash','digest','outcome_unknown')"
                    )
            else:
                db.execute(
                    "INSERT INTO computer_sessions(id,workspace_id,generation,status,created_at,updated_at) VALUES ('computer',?,1,?,?,?)",
                    (wid, "hibernated" if record == "computer" else "closed", stamp(), stamp()),
                )
                if record == "lease":
                    db.execute(
                        "INSERT INTO control_leases(id,bot_id,session_id,generation,user_id,login_digest,client_id,surface,surface_id,viewport_revision,fence,expires_at,status) VALUES ('lease',?,'computer',1,?,'digest','client','browser','browser','rev',1,?,'releasing')",
                        (bid, uid, stamp()),
                    )
        response = client.post(f"/api/workspaces/{wid}/deletions", json=cmd)
        assert response.status_code == 409, response.text
        assert response.json()["detail"]["blockers"]
        assert client.get(f"/api/bots/{bid}").status_code == 200
        with app.state.runtime.store.transaction() as db:
            assert not db.execute("SELECT 1 FROM workspace_cleanup_items").fetchone()


def test_database_fence_rejects_stale_producers_and_identity_reuse(tmp_path):
    app, _, _, _ = _app(tmp_path)
    with TestClient(app) as client:
        user = _register(client)
        wid, bid = workspace_bot(client)
        stale = app.state.catalog.get_bot(user["id"], bid)
        deleted(client, wid)
        operations = (
            lambda db: db.execute(
                "INSERT INTO workspace_channels(workspace_id) VALUES (?)", (wid,)
            ),
            lambda db: db.execute(
                "INSERT INTO bot_streams(bot_id,workspace_id) VALUES (?,?)",
                (bid, "personal_" + user["id"]),
            ),
            lambda db: db.execute(
                "INSERT INTO workspace_members VALUES (?,?,'viewer')", (wid, user["id"])
            ),
            lambda db: db.execute(
                "INSERT INTO computer_sessions(id,workspace_id,generation,status,created_at,updated_at) VALUES ('late',?,1,'provisioning',?,?)",
                (wid, stamp(), stamp()),
            ),
            lambda db: db.execute("UPDATE workspaces SET deleted_at=NULL WHERE id=?", (wid,)),
        )
        for operation in operations:
            with pytest.raises(Conflict, match="deleted"):
                with app.state.runtime.store.transaction() as db:
                    operation(db)
        with pytest.raises(Conflict, match="deleted"):
            app.state.runtime.ensure(stale)


async def test_transfer_admission_is_durable_until_writer_exits(tmp_path):
    app, _, _, _ = _app(tmp_path)
    with TestClient(app) as client:
        _register(client)
        wid, bid = workspace_bot(client)
        async with app.state.runtime.files.transfers.writer(bid):
            preview = client.get(f"/api/workspaces/{wid}/deletion-preview").json()
            assert preview["blockers"][0]["code"] == "transfers_active"
        deleted(client, wid)
        with pytest.raises(Conflict, match="unavailable"):
            async with app.state.runtime.files.transfers.writer(bid):
                raise AssertionError("Deleted workspaces cannot admit file writers")
