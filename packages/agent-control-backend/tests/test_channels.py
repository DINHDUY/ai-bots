import json
import re
from datetime import UTC, datetime, timedelta

import pytest
from agentbot.adapters.anthropic import ClaudeAgentAdapter, ModelTurn, ToolUse
from agentbot.adapters.microsoft import MicrosoftAgentAdapter
from agentbot_tools.ufo import UfoAgentAdapter
from channels_support import post as post
from channels_support import settled as settled
from channels_support import setup as setup
from control_support import _app as _app
from control_support import _create_bot as _create_bot
from control_support import _key as _key
from control_support import _register as _register
from fastapi.testclient import TestClient


@pytest.mark.parametrize("framework", ["microsoft", "anthropic", "ufo"])
def test_real_adapters_reply_without_provisioning_a_computer(tmp_path, framework):
    app, sandboxes, _, _ = _app(tmp_path)
    calls = []

    async def runner(tools, prompt, context, on_text):
        assert "run_terminal_command" not in tools
        roster = json.loads(await tools["list_workspace_bots"]())
        assert {b["name"] for b in roster["bots"]} == {"Writer"}
        mid = re.search(r"request ID (channelmsg_\w+)", prompt)[1]
        calls.append(mid)
        await tools["reply_to_bot"](mid, "The answer is 42.")
        return "Replied"

    class Model:
        def __init__(self):
            self.count = 0

        async def complete(self, *, messages, system):
            self.count += 1
            if self.count == 1:
                mid = re.search(r"request ID (channelmsg_\w+)", json.dumps(messages))[1]
                calls.append(mid)
                return ModelTurn(
                    "tool_use",
                    "",
                    [
                        ToolUse(
                            "reply",
                            "reply_to_bot",
                            None,
                            {"reply_to": mid, "text": "The answer is 42."},
                        )
                    ],
                )
            return ModelTurn("end_turn", "Replied")

    async def completion(messages):
        if any("Peer operation result" in m["content"] for m in messages):
            return json.dumps({"final": "Replied"})
        mid = re.search(r"request ID (channelmsg_\w+)", json.dumps(messages))[1]
        calls.append(mid)
        return json.dumps(
            {
                "peer": {
                    "name": "reply_to_bot",
                    "arguments": {"reply_to": mid, "text": "The answer is 42."},
                }
            }
        )

    app.state.kernel.registry.register_framework(
        framework,
        lambda: (
            MicrosoftAgentAdapter(runner=runner)
            if framework == "microsoft"
            else ClaudeAgentAdapter(client=Model())
            if framework == "anthropic"
            else UfoAgentAdapter(completion=completion)
        ),
    )
    with TestClient(app) as client:
        wid, bots = setup(client, (framework,))
        message = post(client, wid, bots[0])
        state = settled(
            client,
            wid,
            lambda s: any(d["state"] == "completed" for d in s["deliveries"]),
        )
        assert [m["body"] for m in state["messages"] if m["kind"] == "reply"] == [
            "The answer is 42."
        ]
        assert calls == [message["id"]]
        snapshot = client.get(f"/api/bots/{bots[0]}/snapshot").json()
        assert snapshot["computer"] is None
        assert snapshot["run"]["session_id"] is None
        assert not snapshot["pending_approvals"]
        assert sandboxes.created == 0


def test_request_wait_reply_continuation_and_idempotency(tmp_path):
    app, sandboxes, _, _ = _app(tmp_path)
    bots, runs = [], []

    async def runner(tools, prompt, context, on_text):
        runs.append(prompt)
        if "Continue the saved task" in prompt:
            assert "42" in prompt
            await tools["reply_to_bot"](root["id"], "Analyst confirmed 42.")
            return "Finished"
        if "Calculate the answer" in prompt:
            mid = re.search(r"request ID (channelmsg_\w+)", prompt)[1]
            await tools["reply_to_bot"](mid, "42")
            return "Replied"
        request = json.loads(await tools["send_bot_request"](bots[1], "Calculate the answer"))
        duplicate = json.loads(await tools["send_bot_request"](bots[1], "Calculate the answer"))
        assert duplicate["id"] == request["id"]
        await tools["wait_for_reply"](
            json.dumps([request["id"]]), "Finish the answer with Analyst's calculation."
        )
        raise AssertionError("Wait must end the run segment")

    app.state.kernel.registry.register_framework(
        "microsoft", lambda: MicrosoftAgentAdapter(runner=runner)
    )
    with TestClient(app) as client:
        wid, created = setup(client)
        bots.extend(created)
        root = post(client, wid, bots[0])
        replay = post(client, wid, bots[0])
        assert root["id"] == replay["id"]
        state = settled(
            client,
            wid,
            lambda s: any(m["body"] == "Analyst confirmed 42." for m in s["messages"]),
        )
        assert len(runs) == 3
        assert len(state["deliveries"]) == 3
        assert len({d["run_id"] for d in state["deliveries"]}) == 3
        assert state["threads"][0]["runs_used"] == 3
        assert sandboxes.created == 0


def test_membership_expiry_tombstones_and_binding_revocation(tmp_path):
    app, _, _, _ = _app(tmp_path)
    with TestClient(app) as client:
        wid, bots = setup(client)
        directory = f"/api/workspaces/{wid}/bots/directory"
        initial = client.get(directory).json()
        app.state.runtime.accepting = False
        message = post(client, wid, bots[1])
        current = client.get(f"/api/bots/{bots[1]}/tools").json()
        response = client.patch(
            f"/api/bots/{bots[1]}",
            json={
                "tool_selection": [],
                "expected_tools_revision": current["tools_revision"],
            },
        )
        assert response.status_code == 200
        assert any(b["state"] == "disabled" for b in client.get(directory).json()["bots"])
        state = client.get(f"/api/workspaces/{wid}/channel").json()
        assert state["deliveries"][0]["state"] == "cancelled"
        entry = client.get(f"/api/bots/{bots[1]}/collaboration").json()
        assert (
            client.patch(
                f"/api/bots/{bots[1]}/collaboration",
                json={
                    "revision": entry["revision"],
                    "enabled": True,
                    "purpose": "Check calculations",
                },
            ).status_code
            == 200
        )
        new = client.get(f"/api/bots/{bots[1]}/collaboration").json()
        assert new["enrollment_id"] != entry["enrollment_id"]
        assert client.delete(f"/api/bots/{bots[1]}").status_code == 200
        assert any(b["state"] == "removed" for b in client.get(directory).json()["bots"])
        assert (
            client.get(f"/api/workspaces/{wid}/channel/messages").json()["messages"][0]["id"]
            == message["id"]
        )
        with app.state.runtime.store.transaction() as db:
            db.execute(
                "UPDATE workspace_bot_directory SET expires_at=? WHERE bot_id=?",
                (
                    (datetime.now(UTC) - timedelta(seconds=1)).isoformat(),
                    bots[0],
                ),
            )
        final = client.get(directory).json()
        assert final["revision"] > initial["revision"]
        assert any(b["state"] == "expired" for b in final["bots"])


def test_authorization_and_private_publication(tmp_path):
    app, _, _, _ = _app(tmp_path)
    with TestClient(app) as owner, TestClient(app) as other:
        wid, bots = setup(owner, ("ufo",))
        _register(other, "other")
        assert other.get(f"/api/workspaces/{wid}/channel").status_code == 404
        response = owner.post(
            f"/api/workspaces/{wid}/members",
            json={"username": "other", "role": "viewer"},
        )
        assert response.status_code == 200, response.text
        assert (
            other.get(f"/api/workspaces/{wid}/bots/directory").json()["bots"][0]["name"] == "Writer"
        )
        assert other.get(f"/api/bots/{bots[0]}").status_code == 403
        assert (
            other.post(
                f"/api/workspaces/{wid}/channel/messages",
                json={
                    "request_id": "untrusted_request",
                    "recipient_id": bots[0],
                    "text": "Run this",
                },
            ).status_code
            == 403
        )
        assert (
            owner.post(
                f"/api/workspaces/{wid}/channel/messages",
                json={
                    "request_id": "forged_request",
                    "recipient_id": bots[0],
                    "text": "Run this",
                    "sender_bot_id": bots[0],
                },
            ).status_code
            == 422
        )
        private = _create_bot(owner, name="Unpublished", framework="ufo").json()["id"]
        assert private not in {
            b["bot_id"] for b in other.get(f"/api/workspaces/{wid}/bots/directory").json()["bots"]
        }
        assert (
            other.patch(
                f"/api/bots/{private}/collaboration",
                json={"revision": 0, "enabled": True},
            ).status_code
            == 403
        )
