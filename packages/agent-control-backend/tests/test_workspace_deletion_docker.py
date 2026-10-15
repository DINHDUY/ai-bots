"""Workspace deletion requires closed real computers and preserves unrelated ones."""

import pytest
from agentbot.sandbox.docker import DockerSessionManager
from control_support import _app, _register
from fastapi.testclient import TestClient
from test_shared_computer import _create_shared
from workflow_import_support import draft, imported
from workspace_delete_support import cleaned, deleted

pytestmark = pytest.mark.docker


def test_delete_closed_shared_workspace_preserves_other_computer(tmp_path):
    import docker

    app, _, _, _ = _app(tmp_path)
    manager = DockerSessionManager(client=docker.from_env())
    manager.configure_scope("control", app.state.runtime.store.deployment)
    app.state.kernel.sandboxes = manager
    computers = []
    with TestClient(app) as client:
        _register(client)
        first = imported(client, draft(client, count=2))
        second = imported(client, draft(client, count=1), "import_other_workspace")
        try:
            for result in (first, second):
                computers.append(_create_shared(client, result["workspace_id"]))
            wid = first["workspace_id"]
            preview = client.get(f"/api/workspaces/{wid}/deletion-preview").json()
            assert any(b["code"] == "computers_active" for b in preview["blockers"])
            closed = client.post(
                f"/api/workspaces/{wid}/computer/lifecycle",
                json={
                    "request_id": "close_for_deletion",
                    "operation": "close",
                    "generation": computers[0]["generation"],
                },
            )
            assert closed.status_code == 200 and closed.json()["status"] == "completed", closed.text
            deleted(client, wid)
            cleaned(client)
            survivor = client.get(f"/api/workspaces/{second['workspace_id']}/computer").json()
            assert survivor["computer"]["status"] == "running"
            assert len(client.get("/api/bots").json()) == 1
            with app.state.runtime.store.transaction() as db:
                assert not db.execute("PRAGMA foreign_key_check").fetchall()
        finally:
            for result, computer in zip((first, second), computers, strict=False):
                client.post(
                    f"/api/workspaces/{result['workspace_id']}/computer/lifecycle",
                    json={
                        "request_id": "cleanup_deletion_test",
                        "operation": "close",
                        "generation": computer["generation"],
                    },
                )
