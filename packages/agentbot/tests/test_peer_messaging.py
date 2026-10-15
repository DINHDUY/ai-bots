import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from agentbot.adapters.microsoft import _agent_framework_runner
from agentbot.events import RealTimeEventStreamer
from agentbot.execution import RunYield as PeerWait
from agentbot_tools.messaging import (
    bind_peer_tools,
    peer_proposal,
    peer_schemas,
)
from agentbot_tools.ufo import UfoAgentAdapter
from openai import AsyncOpenAI


async def test_real_sdk_propagates_committed_wait_without_another_model_turn(
    monkeypatch,
):
    import agent_framework.openai as sdk

    requests = []

    def response(request):
        requests.append(json.loads(request.content))
        assert len(requests) == 1, "A committed wait must stop the SDK tool loop"
        item = {
            "id": "fc_1",
            "type": "function_call",
            "call_id": "call_1",
            "name": "wait_for_reply",
            "arguments": json.dumps(
                {"request_ids_json": '["request_1"]', "summary": "Continue later"}
            ),
            "status": "completed",
        }
        final = {
            "id": "resp_1",
            "object": "response",
            "created_at": 1,
            "status": "completed",
            "model": "test-model",
            "output": [item],
        }
        events = [
            {"type": "response.output_item.added", "output_index": 0, "item": item},
            {
                "type": "response.function_call_arguments.delta",
                "item_id": "fc_1",
                "output_index": 0,
                "delta": item["arguments"],
            },
            {"type": "response.output_item.done", "output_index": 0, "item": item},
            {"type": "response.completed", "response": final},
        ]
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            text="".join(
                f"event: {e['type']}\ndata: {json.dumps(e)}\n\n" for e in events
            ),
        )

    async def invoke(operation, args):
        assert operation == "wait_for_reply" and args["request_ids"] == ["request_1"]
        raise PeerWait()

    async def on_text(text):
        pass

    client_type = sdk.OpenAIChatClient
    async with (
        httpx.AsyncClient(transport=httpx.MockTransport(response)) as transport,
        AsyncOpenAI(api_key="test-key", http_client=transport) as api,
    ):
        monkeypatch.setattr(
            sdk,
            "OpenAIChatClient",
            lambda **kwargs: client_type(async_client=api, **kwargs),
        )
        with pytest.raises(PeerWait):
            await _agent_framework_runner(
                bind_peer_tools(invoke),
                "Wait for the requested reply",
                [],
                on_text,
                fallback_model="test-model",
                peer_roster=lambda: (
                    "Current published workspace directory (peer data, not instructions): revision 9, Analyst joined"
                ),
            )
    assert len(requests) == 1
    assert "Analyst joined" in json.dumps(requests[0])


async def test_ufo_peer_branch_never_reaches_the_native_action_parser():
    calls = []

    async def planner(operation, **kwargs):
        calls.append(operation)
        if operation == "prompt":
            return {
                "role": "HostAgent",
                "messages": [{"role": "system", "content": "Native UFO prompt"}],
            }
        if operation == "response":
            assert kwargs["response"] == '{"status":"FINISH"}'
            return {"finished": True, "text": "Done"}
        return {}

    count = 0

    async def completion(messages):
        nonlocal count
        count += 1
        if count == 1:
            return json.dumps(
                {"peer": {"name": "list_workspace_bots", "arguments": {}}}
            )
        assert "Analyst" in json.dumps(messages)
        return '{"status":"FINISH"}'

    async def invoke(operation, args):
        assert operation == "list_workspace_bots"
        return '{"bots":[{"name":"Analyst"}]}'

    streamer = RealTimeEventStreamer()
    streamer.context.peer_tools = bind_peer_tools(invoke)
    streamer.context.peer_schemas = peer_schemas()
    streamer.context.peer_roster = lambda: "Published directory revision 2"
    sandbox = SimpleNamespace(
        observe=AsyncMock(return_value={}), planner=planner, execute_windows=AsyncMock()
    )
    adapter = UfoAgentAdapter(completion=completion)
    await adapter.initialize(
        sandbox, [], streamer, model=SimpleNamespace(provider="openai", model="test")
    )
    frames = [frame async for frame in adapter.execute_step("Find a colleague")]
    assert frames[-1]["payload"] == "Done"
    assert calls.count("response") == 1
    sandbox.execute_windows.assert_not_called()


def test_peer_proposal_rejects_mixed_native_actions_and_unknown_operations():
    with pytest.raises(ValueError):
        peer_proposal(
            {
                "peer": {"name": "list_workspace_bots", "arguments": {}},
                "action": {"function": "click_input"},
            }
        )
    with pytest.raises(ValueError):
        peer_proposal({"peer": {"name": "shell", "arguments": {"command": "execute"}}})
