"""Permission revocation and late file cleanup cannot outlive deletion."""

import pytest
from control_support import _app, _register
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect
from test_workspace_deletion_recovery import workspace_bot
from workspace_delete_support import deleted


def test_deletion_revokes_existing_socket_share_and_download(tmp_path):
    app, _, _, _ = _app(tmp_path)
    with TestClient(app) as owner, TestClient(app) as viewer:
        _register(owner)
        _register(viewer, "viewer")
        wid, bid = workspace_bot(owner)
        owner.post(f"/api/workspaces/{wid}/members", json={"username": "viewer", "role": "viewer"})
        blobs = app.state.runtime.files.blobs
        blob = blobs.reserve(bid, "closed", "note.txt", "revision", 7, "text/plain")
        (blobs.directory / blob).write_bytes(b"private")
        share = owner.post(
            f"/api/bots/{bid}/shares", json={"username": "viewer", "artifacts": [blob]}
        )
        assert share.status_code == 200, share.text
        url = f"/api/shares/{share.json()['id']}"
        assert viewer.get(url).status_code == 200
        with viewer.websocket_connect(f"/api/bots/{bid}/events/ws") as socket:
            assert socket.receive_json()["type"] == "snapshot"
            deleted(owner, wid)
            with pytest.raises(WebSocketDisconnect):
                for _ in range(20):
                    socket.receive_json()
        assert viewer.get(url).status_code == 404
        assert owner.get(f"/api/bots/{bid}/artifacts/{blob}/content").status_code == 404
        assert viewer.get(f"/api/bots/{bid}/snapshot").status_code == 404


async def test_failed_staging_cleanup_remains_a_blocker_until_removed(tmp_path, monkeypatch):
    app, _, _, _ = _app(tmp_path)
    with TestClient(app) as client:
        _register(client)
        wid, bid = workspace_bot(client)
        runtime = app.state.runtime
        cleanup = runtime.workspace_deletions.cleanup
        original = cleanup.unlink

        def denied(root, name):
            if name.startswith("staging-"):
                raise PermissionError("locked staging file")
            original(root, name)

        with monkeypatch.context() as patch:
            patch.setattr(cleanup, "unlink", denied)
            async with runtime.files.transfers.writer(bid) as token:
                name = f"staging-{token}-file"
                path = runtime.files.blobs.directory / name
                path.write_bytes(b"staging")
                await runtime.files.transfers.staging(token, name)
            await runtime.store.database.offload(cleanup.sweep)
            preview = client.get(f"/api/workspaces/{wid}/deletion-preview").json()
            assert any(b["code"] == "transfers_active" for b in preview["blockers"])
            assert path.exists()
        await runtime.store.database.offload(cleanup.sweep)
        assert not path.exists()
        deleted(client, wid)
