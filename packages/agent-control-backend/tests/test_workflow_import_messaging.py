"""Imported bots use the actual messaging adapters and durable continuations."""

import json
import re

import pytest
from agentbot.adapters.anthropic import ClaudeAgentAdapter, ModelTurn, ToolUse
from agentbot.adapters.microsoft import MicrosoftAgentAdapter
from channels_support import post, settled
from control_support import _app, _key, _register
from fastapi.testclient import TestClient
from workflow_import_support import draft, imported


@pytest.mark.parametrize(
    "frameworks",
    [
        ("microsoft", "microsoft"),
        ("anthropic", "anthropic"),
        ("microsoft", "anthropic"),
    ],
)
def test_imported_peers_discover_request_reply_and_continue(tmp_path, frameworks):
    app, sandboxes, _, _ = _app(tmp_path)
    bots, calls = [], []
    root = {}

    async def runner(tools, prompt, context, on_text):
        calls.append(prompt)
        directory = json.loads(await tools["list_workspace_bots"]())
        assert {entry["bot_id"] for entry in directory["bots"]} == set(bots)
        if "Continue the saved task" in prompt:
            assert "42" in prompt
            await tools["reply_to_bot"](root["id"], "Research confirmed 42.")
        elif "Calculate the answer." in prompt:
            mid = re.search(r"request ID (channelmsg_\w+)", prompt)[1]
            await tools["reply_to_bot"](mid, "42")
        else:
            request = json.loads(await tools["send_bot_request"](bots[1], "Calculate the answer."))
            await tools["wait_for_reply"](json.dumps([request["id"]]), "Finish with the answer.")
            raise AssertionError("Waiting must release this run slot")
        return "Replied"

    class Model:
        def __init__(self):
            self.step = 0
            self.branch = ""
            self.mid = ""

        async def complete(self, *, messages, system):
            self.step += 1
            text = json.dumps(messages)
            if self.step == 1:
                calls.append(text)
                self.branch = (
                    "resume"
                    if "Continue the saved task" in text
                    else "peer"
                    if "Calculate the answer." in text
                    else "root"
                )
                match = re.search(r"request ID (channelmsg_\w+)", text)
                self.mid = match[1] if match else ""
                return tool("list_workspace_bots", {})
            if self.step == 2:
                directory = json.loads(messages[-1]["content"][0]["content"])
                assert {entry["bot_id"] for entry in directory["bots"]} == set(bots)
                if self.branch == "resume":
                    assert "42" in text
                    return tool(
                        "reply_to_bot", {"reply_to": root["id"], "text": "Research confirmed 42."}
                    )
                if self.branch == "peer":
                    return tool("reply_to_bot", {"reply_to": self.mid, "text": "42"})
                return tool(
                    "send_bot_request", {"recipient_id": bots[1], "text": "Calculate the answer."}
                )
            if self.branch == "root":
                request = json.loads(messages[-1]["content"][0]["content"])
                return tool(
                    "wait_for_reply",
                    {
                        "request_ids_json": json.dumps([request["id"]]),
                        "summary": "Finish with the answer.",
                    },
                )
            return ModelTurn("end_turn", "Replied")

    def tool(name, arguments):
        return ModelTurn("tool_use", "", [ToolUse(name, name, None, arguments)])

    app.state.kernel.registry.register_framework(
        "microsoft", lambda: MicrosoftAgentAdapter(runner=runner)
    )
    app.state.kernel.registry.register_framework(
        "anthropic", lambda: ClaudeAgentAdapter(client=Model())
    )
    with TestClient(app) as client:
        _register(client)
        source = draft(client, count=2, framework=frameworks[0])
        if frameworks[1] != frameworks[0]:
            source["files"][1]["overrides"] = {
                "runtime": {
                    "framework": "anthropic",
                    "credential_id": _key(client, "anthropic")["id"],
                    "model": "claude-sonnet-5",
                }
            }
        result = imported(client, source)
        assert calls == [] and sandboxes.created == 0
        bots.extend(bot["bot_id"] for bot in result["bots"])
        root.update(post(client, result["workspace_id"], bots[0]))
        state = settled(
            client,
            result["workspace_id"],
            lambda s: any(message["body"] == "Research confirmed 42." for message in s["messages"]),
        )
        assert len(calls) == 3
        assert len({delivery["run_id"] for delivery in state["deliveries"]}) == 3
        for bid in bots:
            snapshot = client.get(f"/api/bots/{bid}/snapshot").json()
            assert snapshot["computer"] is None
            assert snapshot["run"]["session_id"] is None
        assert sandboxes.created == 0
