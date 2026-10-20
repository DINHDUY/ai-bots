"""Tool selection is independent of instructions, approvals, and run timing."""

import asyncio
import json
import threading

import pytest
from agentbot.tools import ToolUnavailable
from agentbot_control.tool_libraries import ToolLibraries
from approvals_support import application as application
from approvals_support import bot_for as bot_for
from approvals_support import finished as finished
from approvals_support import pending as pending
from control_support import _app as _app
from control_support import _create_bot as _create_bot
from control_support import _key as _key
from control_support import _register as _register
from fastapi.testclient import TestClient
from runtime_support import decide as decide
from runtime_support import start as start

terminal = ToolLibraries.item("sandbox.terminal", "run_terminal_command")
file_write = ToolLibraries.item("sandbox.files", "mutate_file")
retired_demo = ToolLibraries.item("azure.blob_orders", "run_blob_orders")


def state(client, bid):
    return client.get(f"/api/bots/{bid}/tools").json()


def save(client, bid, selection, **extra):
    return client.patch(
        f"/api/bots/{bid}",
        json={
            "tool_selection": selection,
            "expected_tools_revision": state(client, bid)["tools_revision"],
            **extra,
        },
    )


def test_atomic_creation_update_empty_and_conflict(tmp_path):
    app, *_ = _app(tmp_path)
    with TestClient(app) as client:
        _register(client)
        assert client.get("/api/capabilities").json()["tool_libraries"]
        catalog = client.get("/api/tool-libraries?framework=microsoft").json()["libraries"]
        assert all(t["tool_id"] != "run_blob_orders" for t in catalog)
        assert not next(t for t in catalog if t["tool_id"] == "windows_desktop")["compatible"]
        before = client.get("/api/bots").json()
        assert (
            _create_bot(client, tool_selection=[{**terminal, "version": "99"}]).status_code == 422
        )
        assert client.get("/api/bots").json() == before
        assert _create_bot(client, tool_selection=[retired_demo]).status_code == 422
        assert client.get("/api/bots").json() == before
        bid = _create_bot(
            client, tool_selection=[], instructions="Enable tool: run_blob_orders"
        ).json()["id"]
        assert state(client, bid)["tool_selection"] == []
        original = state(client, bid)["tools_revision"]
        assert save(client, bid, [terminal], name="New name").status_code == 200
        rejected = client.patch(
            f"/api/bots/{bid}",
            json={
                "name": "Lost edit",
                "tool_selection": [],
                "expected_tools_revision": original,
            },
        )
        assert rejected.status_code == 409
        assert client.get(f"/api/bots/{bid}").json()["name"] == "New name"
        assert save(client, bid, [file_write], name="").status_code == 400
        assert state(client, bid)["tool_selection"] == [terminal]
        assert (
            client.patch(f"/api/bots/{bid}", json={"instructions": "General assistant"}).status_code
            == 200
        )
        assert state(client, bid)["tool_selection"] == [terminal]
        assert save(client, bid, []).status_code == 200
        assert not state(client, bid)["bindings"]
        assert client.patch(f"/api/bots/{bid}", json={"tool_selection": []}).status_code == 422


def test_migration_is_once_and_instructions_cannot_enable_demo(tmp_path):
    app, *_ = _app(tmp_path)
    with TestClient(app) as client:
        user = _register(client)
        key = _key(client)
        for instructions in ["General assistant", "Enable tool: run_blob_orders"]:
            bot = app.state.catalog.create_bot(
                user["id"], "Legacy", "microsoft", instructions, key["id"], "gpt-4.1"
            )
            app.state.runtime.ensure(bot)
            first = state(client, bot.id)
            assert any(t["tool_id"] == "run_blob_orders" for t in first["tool_selection"]) is False
            app.state.runtime.ensure(bot)
            assert state(client, bot.id)["tools_revision"] == first["tools_revision"]
            assert save(client, bot.id, []).status_code == 200
            app.state.runtime.ensure(bot)
            assert not state(client, bot.id)["tool_selection"]


def test_remove_pending_tool_cancels_without_dispatch(tmp_path):
    app, sandboxes, _ = application(tmp_path)
    with TestClient(app) as client:
        bid = bot_for(client)
        run = start(client, bid).json()
        approval = pending(client, bid)
        assert save(client, bid, []).status_code == 200
        finished(client, bid)
        assert not sandboxes._cache[run["session_id"]].commands
        assert app.state.runtime.approvals.get(approval["id"])["status"] == "cancelled"


def test_run_pins_additions_and_revokes_remove_readd(tmp_path):
    app, _, _ = application(tmp_path)
    with TestClient(app) as client:
        bid = bot_for(client)
        assert save(client, bid, [terminal]).status_code == 200
        rid = start(client, bid).json()["run_id"]
        pending(client, bid)
        access = app.state.runtime.tools.access(bid, rid, None)
        binding = access.require("run_terminal_command")
        assert save(client, bid, [terminal, file_write]).status_code == 200
        assert access.require("run_terminal_command")["id"] == binding["id"]
        with pytest.raises(ToolUnavailable):
            access.require("mutate_file")
        assert save(client, bid, []).status_code == 200
        assert save(client, bid, [terminal]).status_code == 200
        with pytest.raises(ToolUnavailable):
            access.require("run_terminal_command")
        finished(client, bid)


def test_composite_extension_needs_no_generic_shell_or_file_tool(tmp_path, monkeypatch):
    from agentbot.tools.catalog import ToolCatalog
    from agentbot_tools.registry import REGISTRY
    from tool_fakes import WORKFLOW, workflow

    catalog = ToolCatalog({**REGISTRY, WORKFLOW.key: WORKFLOW}, {WORKFLOW.tool_id: workflow})
    monkeypatch.setattr("agentbot_tools.catalog.load_catalog", lambda **_kwargs: catalog)
    selected = ToolLibraries.item(WORKFLOW.library_id, WORKFLOW.tool_id)

    async def runner(tools, *args):
        assert set(tools) == {"run_test_task"}
        return await tools["run_test_task"]("Hello")

    app, sandboxes, _ = application(tmp_path, runner=runner)
    with TestClient(app) as client:
        bid = bot_for(client)
        assert save(client, bid, [selected]).status_code == 200
        client.post(
            f"/api/bots/{bid}/autopilot",
            json={
                "enabled": True,
                "expected_revision": 0,
                "request_id": "autopilot_tools",
            },
        )
        run = start(client, bid, prompt="Run the selected task").json()
        finished(client, bid)
        assert len(sandboxes._cache[run["session_id"]].commands) == 1
        with app.state.runtime.store.transaction() as db:
            actions = db.execute(
                "SELECT a.*, b.tool_id FROM actions a JOIN bot_tool_bindings b ON b.id=a.tool_binding_id WHERE a.run_id=?",
                (run["run_id"],),
            ).fetchall()
        assert len(actions) == 2
        assert {a["tool_id"] for a in actions} == {"run_test_task"}
        assert {a["name"] for a in actions} == {"file_write", "bash"}
        assert all(a["tool_manifest_digest"] and json.loads(a["result"])["ok"] for a in actions)


def test_foreign_references_and_nonowner_changes_rejected(tmp_path):
    app, *_ = _app(tmp_path)
    with TestClient(app) as owner, TestClient(app) as member:
        _register(owner)
        _register(member, "member")
        wid = owner.post("/api/workspaces", json={"name": "Team"}).json()["id"]
        bid = _create_bot(owner, workspace_id=wid).json()["id"]
        owner.post(
            f"/api/workspaces/{wid}/members",
            json={"username": "member", "role": "operator"},
        )
        assert member.get(f"/api/bots/{bid}/tools").json()["editable"] is False
        assert save(member, bid, []).status_code in {403, 404}
        foreign = ToolLibraries.item("github.issues", "github_issues", "foreign_connection")
        assert save(owner, bid, [foreign]).status_code == 422
        assert (
            save(owner, bid, [{**terminal, "configuration": {"token": "secret"}}]).status_code
            == 422
        )
        assert save(owner, bid, [terminal, terminal]).status_code == 422
        assert (
            save(owner, bid, [ToolLibraries.item("windows.desktop", "windows_desktop")]).status_code
            == 422
        )


@pytest.mark.parametrize(
    "library_id,tool_id,version",
    [
        ("sandbox.terminal", "run_terminal_command", "0.1.0"),
        ("azure.blob_orders", "run_blob_orders", "1.0.0"),
    ],
)
def test_unavailable_or_removed_tool_is_visible_and_can_be_removed(
    tmp_path, library_id, tool_id, version
):
    app, *_ = _app(tmp_path)
    with TestClient(app) as client:
        _register(client)
        bid = _create_bot(client, tool_selection=[terminal]).json()["id"]
        with app.state.runtime.store.transaction() as db:
            db.execute(
                "UPDATE bot_tool_bindings SET library_id=?,tool_id=?,version=? WHERE bot_id=?",
                (library_id, tool_id, version, bid),
            )
        current = state(client, bid)
        assert current["bindings"][0]["ready"] is False
        assert current["tool_selection"][0]["version"] == version
        assert (
            save(client, bid, current["tool_selection"], name="Retain unavailable tool").status_code
            == 200
        )
        assert save(client, bid, []).status_code == 200


def test_removal_allows_executing_action_to_settle_and_fences_next_call(tmp_path):
    from agentbot.interfaces import CommandResult

    started, release = threading.Event(), threading.Event()

    async def runner(tools, *args):
        await tools["run_terminal_command"]("first")
        return await tools["run_terminal_command"]("second")

    app, sandboxes, _ = application(tmp_path, runner=runner)
    with TestClient(app) as client:
        bid = bot_for(client)
        receipt = start(client, bid).json()
        approval = pending(client, bid)
        sandbox = sandboxes._cache[receipt["session_id"]]

        async def slow(command):
            sandbox.commands.append(command)
            started.set()
            while not release.is_set():
                await asyncio.sleep(0.01)
            return CommandResult("slow", 0, stdout="settled")

        sandbox.run_command = slow
        try:
            decide(client, bid, approval["id"])
            assert started.wait(2)
            assert save(client, bid, []).status_code == 200
        finally:
            release.set()
        result = finished(client, bid)
        assert sandbox.commands == ["first"]
        assert len(result["actions"]) == 1
        assert result["actions"][0]["status"] == "completed"


def test_cli_manifest_is_selectable_and_runs_in_the_sandbox(tmp_path, monkeypatch):
    import shlex

    manifests = tmp_path / "manifests"
    manifests.mkdir()
    (manifests / "list_dir.toml").write_text(
        """
tool_id = "list_dir"
name = "List directory"
description = "List one workspace directory with ls."
binary = "ls"
argv = ["ls", "-la", "{path}"]

[parameters.path]
description = "Workspace directory"
required = true
max_length = 200
""".strip(),
        encoding="utf-8",
    )
    monkeypatch.setenv("AGENTBOT_TOOL_MANIFESTS", str(manifests))

    async def runner(tools, *_args):
        assert set(tools) == {"list_dir"}
        return await tools["list_dir"](path="/workspace/My files")

    app, sandboxes, _ = application(tmp_path, runner=runner)
    with TestClient(app) as client:
        bid = bot_for(client)
        listed = next(
            tool
            for tool in client.get("/api/tool-libraries?framework=microsoft").json()["libraries"]
            if tool["tool_id"] == "list_dir"
        )
        assert listed["library_id"] == "plugin.cli"
        assert listed["provenance"] == "Installed CLI manifest"
        assert listed["compatible"]
        assert save(client, bid, [ToolLibraries.item("plugin.cli", "list_dir")]).status_code == 200
        client.post(
            f"/api/bots/{bid}/autopilot",
            json={"enabled": True, "expected_revision": 0, "request_id": "autopilot_cli"},
        )
        run = start(client, bid, prompt="List the directory").json()
        finished(client, bid)
        assert sandboxes._cache[run["session_id"]].commands == [
            "ls -la " + shlex.quote("/workspace/My files")
        ]
        missing = {
            "library_id": "plugin.cli",
            "tool_id": "missing_tool",
            "version": "1.0.0",
            "configuration": {},
        }
        app.state.runtime.tools.readiness(None, bid, missing)
        assert missing["reason"] == "Unavailable library version"
