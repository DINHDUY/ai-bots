"""Instruction boundaries agree across bot writes and workflow imports."""

import pytest
from control_support import _app, _create_bot, _register
from fastapi.testclient import TestClient
from workflow_import_support import draft, imported


@pytest.mark.parametrize("character", ["x", "\U0001f9d1"])
def test_bot_create_and_edit_instruction_limit(tmp_path, character):
    app, _, _, _ = _app(tmp_path)
    instructions = character * 16000
    with TestClient(app) as client:
        _register(client)
        created = _create_bot(client, instructions=instructions)
        assert created.status_code == 201, created.text
        bot = created.json()
        assert bot["instructions"] == instructions
        path = f"/api/bots/{bot['id']}"

        changed = "y" + instructions[1:]
        updated = client.patch(path, json={"instructions": changed})
        assert updated.status_code == 200, updated.text
        assert updated.json()["instructions"] == changed

        rejected = client.patch(path, json={"instructions": instructions + "x"})
        assert rejected.status_code == 400
        assert rejected.json()["detail"] == "Instructions must be 16000 characters or fewer."
        assert client.get(path).json()["instructions"] == changed
        assert (
            _create_bot(
                client, credential_id=bot["credential_id"], instructions=instructions + "x"
            ).status_code
            == 400
        )
        assert len(client.get("/api/bots").json()) == 1


@pytest.mark.parametrize("framework", ["microsoft", "anthropic"])
def test_import_instruction_limit_preserves_body_and_rejects_oversize(tmp_path, framework):
    app, _, _, _ = _app(tmp_path)
    body = "\r\n" + "\U0001f9d1" * 15996 + "\r\n"
    with TestClient(app) as client:
        _register(client)
        source = draft(client, count=1, framework=framework)
        source["files"][0]["content"] = "---\r\nname: Analyst\r\n---\r\n" + body
        result = imported(client, source)
        bot = client.get(f"/api/bots/{result['bots'][0]['bot_id']}").json()
        assert bot["instructions"] == body
        assert app.state.runtime.capabilities["workflow_import_limits"]["instructions"] == 16000

        before = client.get("/api/workspaces").json()
        source["files"][0]["content"] += " "
        preview = client.post("/api/workflow-imports/preview", json=source).json()
        assert not preview["valid"]
        assert preview["files"][0]["instructions"] == body + " "
        assert preview["files"][0]["errors"][0]["code"] == "instructions_size"
        rejected = client.post(
            "/api/workflow-imports",
            json={**source, "request_id": "oversize_import_01", "preview_digest": "0" * 64},
        )
        assert rejected.status_code == 422
        assert client.get("/api/workspaces").json() == before
        assert len(client.get("/api/bots").json()) == 1
