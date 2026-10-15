import re

import pytest
from agentbot.adapters.microsoft import MicrosoftAgentAdapter
from channels_support import post as post
from channels_support import settled as settled
from channels_support import setup as setup
from control_support import _app as _app
from control_support import _create_bot as _create_bot
from control_support import _key as _key
from control_support import _register as _register
from fastapi.testclient import TestClient


def test_artifact_grant_is_explicit_protected_and_revocable(tmp_path):
    import hashlib

    from agentbot_control.event_store import stamp

    app, _, _, _ = _app(tmp_path)
    with TestClient(app) as owner, TestClient(app) as viewer:
        wid, bots = setup(owner)
        _register(viewer, "viewer")
        owner.post(
            f"/api/workspaces/{wid}/members",
            json={"username": "viewer", "role": "viewer"},
        )
        app.state.runtime.accepting = False
        raw = b"A retained answer"
        aid = "blob_channel_fixture"
        (app.state.runtime.files.blobs.directory / aid).write_bytes(raw)
        with app.state.runtime.store.transaction() as db:
            db.execute(
                "INSERT INTO file_blobs VALUES (?,?,?,?,?,?,?,?)",
                (
                    aid,
                    bots[0],
                    "closed-computer",
                    "/workspace/answer.txt",
                    hashlib.sha256(raw).hexdigest(),
                    len(raw),
                    "text/plain",
                    stamp(),
                ),
            )
        post(owner, wid, bots[1], artifact_ids=[aid])
        response = viewer.get(f"/api/workspaces/{wid}/channel/messages").json()
        gid = response["messages"][0]["artifacts"][0]["id"]
        url = f"/api/workspaces/{wid}/channel/artifacts/{gid}"
        assert viewer.get(url).content == raw
        assert owner.post(url + "/revoke").status_code == 200
        assert viewer.get(url).status_code == 404
        with app.state.runtime.store.transaction() as db:
            db.execute("UPDATE file_blobs SET path='/workspace/azure.env' WHERE id=?", (aid,))
        bad = owner.post(
            f"/api/workspaces/{wid}/channel/messages",
            json={
                "request_id": "protected_file",
                "recipient_id": bots[1],
                "text": "Publish",
                "artifact_ids": [aid],
            },
        )
        assert bad.status_code == 409
        assert len(response["messages"]) == 1


def test_channel_computer_actions_still_require_and_recheck_approval(tmp_path):
    from runtime_support import decide, start, wait_state

    app, sandboxes, _, _ = _app(tmp_path)

    async def runner(tools, prompt, context, on_text):
        if prompt == "Prepare the computer":
            return "Ready"
        await tools["run_terminal_command"]("echo approved")
        mid = re.search(r"request ID (channelmsg_\w+)", prompt)[1]
        await tools["reply_to_bot"](mid, "Executed")
        return "Finished"

    app.state.kernel.registry.register_framework(
        "microsoft", lambda: MicrosoftAgentAdapter(runner=runner)
    )
    with TestClient(app) as client:
        wid, bots = setup(client)
        bid = bots[0]
        selected = client.get(f"/api/bots/{bid}/tools").json()
        selected["tool_selection"].append(
            {
                "library_id": "sandbox.terminal",
                "tool_id": "run_terminal_command",
                "version": "1.0.0",
                "configuration": {},
            }
        )
        assert (
            client.patch(
                f"/api/bots/{bid}",
                json={
                    "tool_selection": selected["tool_selection"],
                    "expected_tools_revision": selected["tools_revision"],
                },
            ).status_code
            == 200
        )
        assert start(client, bid, prompt="Prepare the computer").status_code == 202
        state = wait_state(client, bid, lambda s: s["run"]["status"] == "completed")
        sandbox = sandboxes._cache[state["computer"]["id"]]
        post(client, wid, bid, requires_computer=True)
        state = wait_state(client, bid, lambda s: bool(s["pending_approvals"]))
        assert not sandbox.commands
        assert state["pending_approvals"][0]["action"] == "bash"
        config = client.get(f"/api/workspaces/{wid}/channel").json()
        assert (
            client.patch(
                f"/api/workspaces/{wid}/channel",
                json={"revision": config["revision"], "enabled": False},
            ).status_code
            == 200
        )
        response = decide(client, bid, state["pending_approvals"][0]["id"])
        assert response.status_code in {200, 409}
        wait_state(
            client,
            bid,
            lambda s: (
                s["run"]["status"] not in {"preparing", "running", "awaiting_approval", "stopping"}
            ),
        )
        assert not sandbox.commands


def test_group_descendants_share_root_budget_and_revocation(tmp_path):
    from agentbot_control.schemas import Conflict

    app, _, _, _ = _app(tmp_path)
    with TestClient(app) as client:
        wid, bots = setup(client)
        runtime = app.state.runtime
        runtime.accepting = False
        group = client.post(
            f"/api/workspaces/{wid}/groups", json={"name": "Writers", "bot_ids": bots}
        ).json()
        handoffs = client.post(
            f"/api/groups/{group['id']}/messages",
            json={
                "request_id": "group_channel_test",
                "task": "@group Describe your role",
                "budget": 2,
            },
        ).json()
        assert isinstance(handoffs, list), handoffs
        for handoff in handoffs:
            with runtime.store.transaction() as db:
                row = db.execute("SELECT * FROM handoffs WHERE id=?", (handoff["id"],)).fetchone()
                bot = runtime.catalog.get_bot_by_id_tx(db, row["target_bot_id"])
            response, _ = runtime.store.admit(
                bot,
                bot.owner_id,
                "handoff_" + row["id"],
                "Describe your role",
                "handoff",
                run_mode="communication",
            )
            runtime.store.finish(bot.id, response["run_id"], "completed")
        with runtime.store.transaction() as db:
            contexts = db.execute("SELECT * FROM channel_run_context").fetchall()
            assert len({r["thread_id"] for r in contexts}) == 1
            thread = db.execute("SELECT * FROM channel_threads").fetchone()
            assert thread["runs_used"] == thread["run_limit"] == 2
            db.execute(
                "DELETE FROM group_members WHERE group_id=? AND bot_id=?",
                (group["id"], bots[1]),
            )
            with pytest.raises(Conflict, match="Group no longer"):
                runtime.channels._thread(db, thread["id"], wid, thread["principal_id"])
