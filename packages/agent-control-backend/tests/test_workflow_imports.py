"""Transactional imports, permissions, and durable response recovery."""

import copy
from concurrent.futures import ThreadPoolExecutor

import pytest
from control_support import _app, _create_bot, _register
from fastapi.testclient import TestClient
from workflow_import_support import command, draft, imported


def test_exact_instructions_shared_settings_and_complete_enrollment(tmp_path):
    app, sandboxes, _, _ = _app(tmp_path)
    with TestClient(app) as client:
        _register(client)
        source = draft(client)
        before = client.get("/api/workspaces").json()
        cmd = command(client, source)
        assert client.get("/api/workspaces").json() == before
        assert client.get("/api/bots").json() == []
        response = client.post("/api/workflow-imports", json=cmd)
        assert response.status_code == 201, response.text
        result = response.json()
        wid = result["workspace_id"]
        assert len(result["bots"]) == 3
        settings = client.get(f"/api/workspaces/{wid}/computer").json()
        assert settings["mode"] == "shared" and settings["provider"] == "docker"
        assert settings["computer"] is None
        channel = client.get(f"/api/workspaces/{wid}/channel").json()
        assert channel["enabled"] and not channel["enroll_future"]
        for index, item in enumerate(result["bots"]):
            bid = item["bot_id"]
            bot = client.get(f"/api/bots/{bid}").json()
            assert bot["instructions"] == f"\r\n# Agent {index}\r\n  Instructions  \r\n"
            assert bot["default_prompt"] == ""
            participation = client.get(f"/api/bots/{bid}/collaboration").json()
            assert participation["state"] == "enabled" and participation["published"]
            assert participation["purpose"] == f"Role {index}"
            tools = client.get(f"/api/bots/{bid}/tools").json()
            assert any(
                tool["library_id"] == "workspace.messaging" for tool in tools["tool_selection"]
            )
        assert sandboxes.created == 0
        assert client.get(f"/api/workflow-imports/{cmd['request_id']}").json() == result
        assert client.post("/api/workflow-imports", json=cmd).json() == result
        changed = {**cmd, "workspace_name": "Different"}
        assert client.post("/api/workflow-imports", json=changed).status_code == 409


@pytest.mark.parametrize("stage", ["bot", "enrollment", "receipt"])
def test_failure_rolls_back_every_resource(tmp_path, monkeypatch, stage):
    app, _, _, _ = _app(tmp_path)
    with TestClient(app, raise_server_exceptions=False) as client:
        _register(client)
        cmd = command(client, draft(client))
        before = client.get("/api/workspaces").json()
        from agentbot_control.repositories import workflow_imports

        obj, method = {
            "bot": (app.state.catalog, "create_bot"),
            "enrollment": (app.state.runtime.channels, "enroll"),
            "receipt": (workflow_imports, "save"),
        }[stage]
        original = getattr(obj, method)

        def fail(*args, **kwargs):
            original(*args, **kwargs)
            raise RuntimeError("Injected failure after write")

        with monkeypatch.context() as patch:
            patch.setattr(obj, method, fail)
            assert client.post("/api/workflow-imports", json=cmd).status_code == 500
        assert client.get("/api/workspaces").json() == before
        assert client.get("/api/bots").json() == []
        assert client.get(f"/api/workflow-imports/{cmd['request_id']}").status_code == 404
        with app.state.runtime.store.transaction() as db:
            for table in (
                "workspace_computer_settings",
                "workspace_bot_directory",
                "workspace_channel_events",
            ):
                assert db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0
        assert client.post("/api/workflow-imports", json=cmd).status_code == 201


def test_concurrent_retry_and_restart_replay(tmp_path, monkeypatch):
    app, _, _, _ = _app(tmp_path)
    with TestClient(app) as client:
        _register(client)
        cmd = command(client, draft(client))
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(
                pool.map(lambda _: client.post("/api/workflow-imports", json=cmd), range(2))
            )
        assert all(result.status_code == 201 for result in results)
        assert results[0].json() == results[1].json()
        result = results[0].json()
        assert (
            len(client.get("/api/bots", params={"workspace_id": result["workspace_id"]}).json())
            == 3
        )
    second, _, _, _ = _app(tmp_path)
    with TestClient(second) as client:
        assert (
            client.post("/api/login", json={"username": "ada", "password": "password1"}).status_code
            == 200
        )
        monkeypatch.setattr("agentbot_control.workflow_imports.service.PARSER_VERSION", "upgraded")
        second.state.runtime.channels.enabled = False
        assert client.post("/api/workflow-imports", json=cmd).json() == result
        assert client.get(f"/api/workflow-imports/{cmd['request_id']}").json() == result


def test_stale_preview_and_credential_revocation(tmp_path):
    app, _, _, _ = _app(tmp_path)
    with TestClient(app) as client:
        _register(client)
        cmd = command(client, draft(client))
        changed = copy.deepcopy(cmd)
        changed["files"][0]["content"] += "changed"
        assert client.post("/api/workflow-imports", json=changed).status_code == 409
        key = cmd["defaults"]["credential_id"]
        assert client.delete(f"/api/credentials/{key}").status_code == 200
        assert client.post("/api/workflow-imports", json=cmd).status_code == 422
        assert client.get("/api/bots").json() == []


def test_foreign_credentials_receipts_and_disabled_capability(tmp_path):
    app, _, _, _ = _app(tmp_path)
    with TestClient(app) as owner, TestClient(app) as other:
        _register(owner)
        source = draft(owner)
        result = imported(owner, source)
        _register(other, "other")
        assert other.get(f"/api/workflow-imports/{result['request_id']}").status_code == 404
        preview = other.post("/api/workflow-imports/preview", json=source).json()
        assert not preview["valid"]
        assert preview["files"][0]["errors"][0]["code"] == "credential"
        app.state.runtime.channels.enabled = False
        assert owner.post("/api/workflow-imports/preview", json=source).status_code == 409


def test_explicit_empty_tools_and_legacy_trimming(tmp_path):
    app, _, _, _ = _app(tmp_path)
    with TestClient(app) as client:
        _register(client)
        source = draft(client, count=1)
        source["defaults"]["tool_selection"] = []
        result = imported(client, source)
        tools = client.get(f"/api/bots/{result['bots'][0]['bot_id']}/tools").json()
        assert [item["library_id"] for item in tools["tool_selection"]] == ["workspace.messaging"]
        legacy = _create_bot(client, instructions=" \nlegacy \n").json()
        assert legacy["instructions"] == "legacy"
        workspace = client.post("/api/workspaces", json={"name": "Ordinary"}).json()
        assert client.get(f"/api/workspaces/{workspace['id']}/computer").json()["mode"] == "per_bot"


@pytest.mark.parametrize(
    "change",
    [
        {"framework": "ufo"},
        {"framework": "anthropic"},
        {"model": "bad model"},
        {"tool_selection": [{"library_id": "bad", "tool_id": "bad", "version": "1"}]},
    ],
)
def test_invalid_runtime_choices(tmp_path, change):
    app, _, _, _ = _app(tmp_path)
    with TestClient(app) as client:
        _register(client)
        source = draft(client)
        source["defaults"].update(change)
        preview = client.post("/api/workflow-imports/preview", json=source).json()
        assert not preview["valid"]
        assert all(file["errors"] for file in preview["files"])


def test_identical_sources_create_distinct_bots_after_name_review(tmp_path):
    app, _, _, _ = _app(tmp_path)
    with TestClient(app) as client:
        _register(client)
        source = draft(client, count=2)
        source["files"][1]["content"] = source["files"][0]["content"]
        preview = client.post("/api/workflow-imports/preview", json=source).json()
        assert not preview["valid"]
        source["files"][1]["overrides"] = {"name": "Second agent"}
        result = imported(client, source)
        assert len({bot["bot_id"] for bot in result["bots"]}) == 2
        assert len({bot["source_hash"] for bot in result["bots"]}) == 1
