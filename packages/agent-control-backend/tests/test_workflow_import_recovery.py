"""Cancellation and deletion do not turn a committed request into a fresh import."""

import asyncio
import json
import threading

import pytest
from agentbot_control.repositories import workflow_imports as receipts
from agentbot_control.workflow_imports.schemas import ImportCommand
from control_support import _app, _register
from fastapi.testclient import TestClient
from workflow_import_support import command, draft


@pytest.mark.asyncio
async def test_cancellation_settles_worker_and_recovers_receipt(tmp_path, monkeypatch):
    app, _, _, _ = _app(tmp_path)
    service = app.state.runtime.workflow_imports
    entered, release = threading.Event(), threading.Event()
    original = receipts.save

    def pause(*args, **kwargs):
        original(*args, **kwargs)
        entered.set()
        assert release.wait(5)

    with TestClient(app) as client:
        owner = _register(client)["id"]
        payload = command(client, draft(client, count=2))
        with monkeypatch.context() as patch:
            patch.setattr(receipts, "save", pause)
            task = asyncio.create_task(service.commit(owner, ImportCommand.model_validate(payload)))
            try:
                assert await asyncio.to_thread(entered.wait, 5)
                task.cancel()
                await asyncio.sleep(0)
                assert not task.done()
            finally:
                release.set()
            with pytest.raises(asyncio.CancelledError):
                await task
        result = client.get(f"/api/workflow-imports/{payload['request_id']}")
        assert result.status_code == 200
        assert client.post("/api/workflow-imports", json=payload).json() == result.json()


def test_receipt_survives_bot_and_credential_deletion(tmp_path):
    app, _, _, _ = _app(tmp_path)
    with TestClient(app) as client:
        _register(client)
        payload = command(client, draft(client, count=1))
        response = client.post("/api/workflow-imports", json=payload)
        assert response.status_code == 201
        result = response.json()
        assert client.delete(f"/api/bots/{result['bots'][0]['bot_id']}").status_code == 200
        assert (
            client.delete(f"/api/credentials/{payload['defaults']['credential_id']}").status_code
            == 200
        )
        assert client.post("/api/workflow-imports", json=payload).json() == result
        assert client.get("/api/bots", params={"workspace_id": result["workspace_id"]}).json() == []


def test_strict_input_and_body_limit_do_not_leak_source(tmp_path):
    app, _, _, _ = _app(tmp_path)
    with TestClient(app) as client:
        _register(client)
        source = draft(client, count=1)
        source["owner_id"] = "forged"
        response = client.post("/api/workflow-imports/preview", json=source)
        assert response.status_code == 422
        assert "Instructions" not in response.text and "forged" not in response.text
        source.pop("owner_id")
        source["files"][0]["content"] = "\ud800"
        response = client.post(
            "/api/workflow-imports/preview",
            content=json.dumps(source),
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code == 422
        response = client.post(
            "/api/workflow-imports/preview",
            content=b"x" * 1048577,
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code == 413
