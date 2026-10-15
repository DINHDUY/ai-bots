"""Deletion is atomic, owned, and independent of import retry history."""

import copy

from control_support import _app, _create_bot, _register
from fastapi.testclient import TestClient
from workflow_import_support import command, draft
from workspace_delete_support import cleaned, deleted, deletion


def test_import_deletion_preserves_other_workspace_and_import_receipt(tmp_path):
    app, _, sessions, _ = _app(tmp_path)
    with TestClient(app) as client:
        user = _register(client)
        other = _create_bot(client).json()
        source = command(client, draft(client))
        imported = client.post("/api/workflow-imports", json=source).json()
        wid = imported["workspace_id"]
        for bot in imported["bots"]:
            sessions.save(bot["bot_id"], [{"role": "user", "content": "Private"}])
        prefs = client.get("/api/preferences").json()
        client.post("/api/preferences", json={**prefs, "workspace_id": wid})
        keys = client.get("/api/credentials").json()
        cmd, result = deleted(client, wid)
        assert result["counts"]["bots"] == 3
        assert client.get("/api/bots").json()[0]["id"] == other["id"]
        assert client.get("/api/credentials").json() == keys
        assert client.get("/api/preferences").json()["workspace_id"] == "personal_" + user["id"]
        assert wid not in [w["id"] for w in client.get("/api/workspaces").json()]
        assert client.get(f"/api/workspaces/{wid}/channel").status_code == 404
        assert client.post(f"/api/workspaces/{wid}/deletions", json=cmd).status_code in (200, 202)
        changed = {**cmd, "confirm_name": "Different"}
        assert client.post(f"/api/workspaces/{wid}/deletions", json=changed).status_code == 409
        assert client.post("/api/workflow-imports", json=source).json() == imported
        assert len(client.get("/api/bots").json()) == 1
        cleaned(client)
        for bot in imported["bots"]:
            assert not sessions._path(bot["bot_id"]).exists()
        with app.state.runtime.store.transaction() as db:
            assert db.execute("PRAGMA foreign_key_check").fetchall() == []
            assert db.execute("SELECT deleted_at FROM workspaces WHERE id=?", (wid,)).fetchone()[0]


def test_empty_personal_permissions_and_stale_preview(tmp_path):
    app, _, _, _ = _app(tmp_path)
    with TestClient(app) as owner, TestClient(app) as other:
        user = _register(owner)
        _register(other, "bea")
        personal = "personal_" + user["id"]
        p = owner.get(f"/api/workspaces/{personal}/deletion-preview").json()
        assert p["blockers"][0]["code"] == "workspace_protected"
        assert (
            owner.post(
                f"/api/workspaces/{personal}/deletions",
                json={
                    "request_id": "protected_01",
                    "confirm_name": p["workspace_name"],
                    "preview_digest": p["preview_digest"],
                },
            ).status_code
            == 409
        )
        wid = owner.post("/api/workspaces", json={"name": "Empty"}).json()["id"]
        cmd = deletion(owner, wid)
        for role in ("viewer", "operator"):
            owner.post(f"/api/workspaces/{wid}/members", json={"username": "bea", "role": role})
            assert other.get(f"/api/workspaces/{wid}/deletion-preview").status_code == 404
            assert other.post(f"/api/workspaces/{wid}/deletions", json=cmd).status_code == 404
        assert owner.post(f"/api/workspaces/{wid}/deletions", json=cmd).status_code == 409
        cmd, _ = deleted(owner, wid)
        assert other.get(f"/api/workspace-deletions/{cmd['request_id']}").status_code == 404
        assert other.get("/api/workspace-deletions").json()["items"] == []
        assert (
            owner.get("/api/workspace-deletions").json()["items"][0]["cleanup"]["state"]
            == "complete"
        )


def test_failure_rolls_back_content_preferences_and_cleanup(tmp_path, monkeypatch):
    app, _, _, _ = _app(tmp_path)
    with TestClient(app, raise_server_exceptions=False) as client:
        _register(client)
        imported = client.post("/api/workflow-imports", json=command(client, draft(client))).json()
        wid = imported["workspace_id"]
        cmd = deletion(client, wid)
        before = copy.deepcopy(client.get("/api/workspaces").json())
        from agentbot_control.repositories import workspace_deletion_commands as service

        original = service.purge

        def failed(*args):
            original(*args)
            raise RuntimeError("Failure after catalog removal")

        with monkeypatch.context() as patch:
            patch.setattr(service, "purge", failed)
            assert client.post(f"/api/workspaces/{wid}/deletions", json=cmd).status_code == 500
        assert client.get("/api/workspaces").json() == before
        assert len(client.get("/api/bots").json()) == 3
        assert client.get(f"/api/workspace-deletions/{cmd['request_id']}").status_code == 404
        with app.state.runtime.store.transaction() as db:
            assert db.execute("SELECT COUNT(*) FROM workspace_cleanup_items").fetchone()[0] == 0
        assert client.post(f"/api/workspaces/{wid}/deletions", json=cmd).status_code == 202
