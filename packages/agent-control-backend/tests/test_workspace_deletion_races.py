"""Admission, migration, and cancellation boundaries for workspace deletion."""

import asyncio
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from agentbot_control.db import Database
from agentbot_control.workspace_deletions.schemas import DeleteCommand
from control_support import _app, _key, _register
from fastapi.testclient import TestClient
from workspace_delete_support import deletion


def test_create_bot_that_already_passed_authorization_cannot_outlive_deletion(
    tmp_path, monkeypatch
):
    app, _, _, _ = _app(tmp_path)
    entered, release = threading.Event(), threading.Event()
    with TestClient(app) as client:
        owner = _register(client)["id"]
        key = _key(client)["id"]
        wid = client.post("/api/workspaces", json={"name": "Race"}).json()["id"]
        command = DeleteCommand.model_validate(deletion(client, wid))
        original = app.state.runtime.workspaces.role

        def role(user_id, workspace_id, owner=False):
            result = original(user_id, workspace_id, owner)
            if workspace_id == wid and owner:
                entered.set()
                assert release.wait(5)
            return result

        monkeypatch.setattr(app.state.runtime.workspaces, "role", role)
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(
                client.post,
                "/api/bots",
                json={
                    "name": "Late",
                    "framework": "microsoft",
                    "instructions": "body",
                    "credential_id": key,
                    "model": "gpt-4.1",
                    "workspace_id": wid,
                },
            )
            try:
                assert entered.wait(5)
                # The legacy create handler runs synchronously on its ASGI loop.
                # Delete through the independent persistence worker while it is paused.
                asyncio.run(app.state.runtime.workspace_deletions.delete(owner, wid, command))
            finally:
                release.set()
            response = future.result(5)
        assert response.status_code == 409, response.text
        assert client.get("/api/bots").json() == []


async def test_cancelled_waiter_retains_committed_receipt(tmp_path, monkeypatch):
    app, _, _, _ = _app(tmp_path)
    entered, release = threading.Event(), threading.Event()
    with TestClient(app) as client:
        owner = _register(client)["id"]
        wid = client.post("/api/workspaces", json={"name": "Cancellation"}).json()["id"]
        cmd = DeleteCommand.model_validate(deletion(client, wid))
        from agentbot_control.repositories import workspace_deletion_commands as service

        original = service.purge

        def pause(*args):
            result = original(*args)
            entered.set()
            assert release.wait(5)
            return result

        monkeypatch.setattr(service, "purge", pause)
        task = asyncio.create_task(app.state.runtime.workspace_deletions.delete(owner, wid, cmd))
        try:
            assert await asyncio.to_thread(entered.wait, 5)
            task.cancel()
        finally:
            release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert client.get(f"/api/workspace-deletions/{cmd.request_id}").status_code == 200
        assert wid not in [w["id"] for w in client.get("/api/workspaces").json()]


def test_upgrade_populated_previous_schema_and_protect_personal(tmp_path, monkeypatch):
    original = Path.glob

    def previous(path, pattern):
        return [p for p in original(path, pattern) if p.name < "021_workspace_deletions.sql"]

    path = tmp_path / "upgrade.sqlite"
    with monkeypatch.context() as patch:
        patch.setattr(Path, "glob", previous)
        db = Database(path)
        with db.transaction() as connection:
            connection.execute("INSERT INTO users VALUES ('owner','owner','hash','date')")
            connection.execute("INSERT INTO workspaces VALUES ('team','owner','Team')")
            connection.execute(
                "INSERT INTO workspaces VALUES ('personal_owner','owner','Personal workspace')"
            )
            connection.execute("INSERT INTO workspace_members VALUES ('team','owner','owner')")
        db.close()
    upgraded = Database(path)
    try:
        assert (
            upgraded.connection.execute(
                "SELECT name,deleted_at FROM workspaces WHERE id='team'"
            ).fetchone()[0]
            == "Team"
        )
        with pytest.raises(sqlite3.IntegrityError, match="workspace_protected"):
            with upgraded.transaction() as connection:
                connection.execute(
                    "UPDATE workspaces SET deleted_at='date' WHERE id='personal_owner'"
                )
        assert not upgraded.connection.execute("PRAGMA foreign_key_check").fetchall()
    finally:
        upgraded.close()


def test_cleanup_rejects_untrusted_ids_and_changed_storage_root(tmp_path, monkeypatch):
    app, _, _, _ = _app(tmp_path)
    cleanup = app.state.runtime.workspace_deletions.cleanup
    outsider = tmp_path / "keep.txt"
    outsider.write_text("keep", encoding="utf-8")
    with pytest.raises(OSError, match="identity"):
        cleanup.remove("artifact", "../../keep.txt")
    original = Path.resolve

    def redirected(path, *args, **kwargs):
        root = cleanup.blobs / "artifacts"
        if path == root or path.parent == root:
            return tmp_path / "outside" / path.relative_to(root)
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "resolve", redirected)
    with pytest.raises(OSError, match="Unsafe"):
        cleanup.remove("artifact", "blob_" + "a" * 32)
    assert outsider.read_text(encoding="utf-8") == "keep"
