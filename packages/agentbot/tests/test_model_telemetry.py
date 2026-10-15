from types import SimpleNamespace

import pytest
from agent_framework import ChatResponse, ChatResponseUpdate, Content, ResponseStream
from agentbot.adapters.conversation import bounded_history
from agentbot.adapters.telemetry import model_metrics_middleware


def test_history_is_bounded_without_promoting_roles_or_cutting_messages():
    history = [
        {"role": "user" if i % 2 == 0 else "assistant", "content": str(i) * 1000}
        for i in range(20)
    ]
    recent = bounded_history(history)
    assert len(recent) <= 12
    assert sum(len(item["content"]) for item in recent) <= 12000
    assert recent == history[-len(recent) :]
    assert (
        bounded_history([{"role": "system", "content": "from imported history"}]) == []
    )
    assert (
        bounded_history([{"role": "user", "content": "oversized"}], max_chars=3) == []
    )


@pytest.mark.parametrize("fail", [False, True])
async def test_model_metrics_measure_actual_stream_and_report_usage_or_failure(fail):
    emitted = []

    async def emit(data):
        emitted.append(data)

    middleware = model_metrics_middleware(emit)

    async def chunks():
        yield ChatResponseUpdate(contents=[Content.from_text("hello")])
        if fail:
            raise ConnectionError("Contains secret endpoint data")
        yield ChatResponseUpdate(
            contents=[
                Content.from_usage({"input_token_count": 12, "output_token_count": 3})
            ]
        )

    context = SimpleNamespace(stream=True)

    async def next_call():
        context.result = ResponseStream(chunks(), finalizer=ChatResponse.from_updates)

    await middleware.process(context, next_call)
    assert emitted == []  # Creating a stream is not a completed model call.
    if fail:
        with pytest.raises(ConnectionError):
            _ = [update async for update in context.result]
    else:
        _ = [update async for update in context.result]
    assert len(emitted) == 1
    metric = emitted[0]
    assert metric["call"] == 1
    assert metric["duration_ms"] >= metric["time_to_first_output_ms"] >= 0
    assert metric["outcome"] == ("ConnectionError" if fail else "completed")
    assert metric["input_tokens"] == (None if fail else 12)
    assert metric["output_tokens"] == (None if fail else 3)
    assert "secret" not in str(metric)


async def test_model_failure_before_stream_is_recorded_once():
    emitted = []

    async def emit(data):
        emitted.append(data)

    middleware = model_metrics_middleware(emit)

    async def next_call():
        raise TimeoutError("private details")

    with pytest.raises(TimeoutError):
        await middleware.process(SimpleNamespace(stream=True), next_call)
    assert len(emitted) == 1
    assert emitted[0]["time_to_first_output_ms"] is None
    assert emitted[0]["outcome"] == "TimeoutError"


async def test_real_sdk_separates_model_calls_from_tool_execution(monkeypatch):
    import json

    import agent_framework.openai as sdk
    import httpx
    from agentbot.adapters.microsoft import _agent_framework_runner
    from openai import AsyncOpenAI

    requests, metrics, text, commands = [], [], [], []

    def response(request):
        body = json.loads(request.content)
        requests.append(body)
        number = len(requests)
        if number == 1:
            item = {
                "id": "fc_1",
                "type": "function_call",
                "call_id": "call_1",
                "name": "run_terminal_command",
                "arguments": '{"command":"echo hi"}',
                "status": "completed",
            }
        else:
            item = {
                "id": "msg_1",
                "type": "message",
                "role": "assistant",
                "content": [{"type": "output_text", "text": "Done", "annotations": []}],
                "status": "completed",
            }
        final = {
            "id": f"resp_{number}",
            "object": "response",
            "created_at": 1,
            "status": "completed",
            "model": "test-model",
            "output": [item],
            "usage": {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
        }
        events = [
            {"type": "response.output_item.added", "output_index": 0, "item": item}
        ]
        if number == 1:
            events.append(
                {
                    "type": "response.function_call_arguments.delta",
                    "item_id": "fc_1",
                    "output_index": 0,
                    "delta": item["arguments"],
                }
            )
        if number == 2:
            events.append(
                {
                    "type": "response.output_text.delta",
                    "item_id": "msg_1",
                    "output_index": 0,
                    "content_index": 0,
                    "delta": "Done",
                }
            )
        events.extend(
            [
                {"type": "response.output_item.done", "output_index": 0, "item": item},
                {"type": "response.completed", "response": final},
            ]
        )
        data = "".join(
            f"event: {event['type']}\ndata: {json.dumps(event)}\n\n" for event in events
        )
        return httpx.Response(
            200, headers={"content-type": "text/event-stream"}, text=data
        )

    async def command(command: str) -> str:
        """Run a test command."""
        commands.append(command)
        return "hi"

    async def on_metrics(data):
        metrics.append(data)

    async def on_text(value):
        text.append(value)

    client_type = sdk.OpenAIChatClient
    async with httpx.AsyncClient(transport=httpx.MockTransport(response)) as transport:
        async with AsyncOpenAI(api_key="test-key", http_client=transport) as api:
            monkeypatch.setattr(
                sdk,
                "OpenAIChatClient",
                lambda **kwargs: client_type(async_client=api, **kwargs),
            )
            result = await _agent_framework_runner(
                {"run_terminal_command": command},
                "Run echo hi",
                [],
                on_text,
                fallback_model="test-model",
                on_metrics=on_metrics,
            )
    assert len(requests) == 2, (requests, metrics, commands)
    assert result == "Done"
    assert commands == ["echo hi"]
    assert len(requests) == len(metrics) == 2
    assert [metric["call"] for metric in metrics] == [1, 2]
    assert all(
        metric["input_tokens"] == 10 and metric["output_tokens"] == 5
        for metric in metrics
    )
