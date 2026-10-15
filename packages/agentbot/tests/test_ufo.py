from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from agentbot.events import RunContext
from agentbot_tools.ufo import UfoAgentAdapter
from agentbot_windows.execution import ActionNotDispatched


@pytest.mark.parametrize("rejection,expected", [
    (ActionNotDispatched("stale_target: moved", "stale_target").result(), 3),
    (ActionNotDispatched("expired", "permit_expired").result(), 3),
    (ActionNotDispatched("Use type_text", "text_method_changed").result(), 3),
    (ActionNotDispatched("Click the editor first", "editor_not_focused").result(), 3),
    (ActionNotDispatched("read-only", "unsupported_text_control").result(), 1),
    ({"ok": False, "dispatched": True, "outcome_unknown": False, "code": "stale_target"}, 1),
    ({"ok": False, "dispatched": False, "outcome_unknown": True, "code": "stale_target"}, 1),
])
async def test_refresh_is_bounded_and_only_follows_proven_non_dispatch(rejection, expected):
    proposals, observations = [], []

    async def observe():
        observations.append(f"observation-{len(observations)}")
        return {"observation_id": observations[-1]}

    async def planner(operation, **kwargs):
        if operation == "prompt": return {"role": "AppAgent", "messages": []}
        if operation == "response": return {"action": {
            "function": "set_edit_text", "observation_id": observations[-1],
            "window_id": "10", "control_id": "2", "arguments": {"text": "Hello"},
        }}
        return {}

    async def execute_windows(action):
        return rejection

    async def execute_action(engine, name, action, detail, execute):
        proposals.append(action)
        yield await execute()

    async def completion(messages): return "fixture"
    adapter = UfoAgentAdapter(completion=completion)
    await adapter.initialize(
        SimpleNamespace(observe=observe, planner=planner, execute_windows=execute_windows),
        [], SimpleNamespace(execute_action=execute_action, emit_log=lambda *args: {}, context=RunContext()),
        model=SimpleNamespace(provider="openai", model="fixture"),
    )
    async for _ in adapter.execute_step("Write Hello"):
        pass
    assert len(proposals) == expected
    assert len({action["observation_id"] for action in proposals}) == expected


@pytest.mark.parametrize("recovers", [True, False])
async def test_read_failure_after_click_never_replays_the_completed_action(monkeypatch, recovers):
    from agentbot_windows.native import NativeDesktop

    class ElementUnavailable(Exception):
        hresult = -2147220991

    desktop = NativeDesktop.__new__(NativeDesktop)
    desktop.observations, desktop.window = {}, None
    responses = [{"observation_id": "observation-before"}, ElementUnavailable()]
    responses += [{"observation_id": "observation-after"}] if recovers else [ElementUnavailable(), ElementUnavailable()]
    desktop.observe = Mock(side_effect=responses)
    monkeypatch.setattr("agentbot_windows.win_session.session_check", lambda: (True, "test", ""))
    monkeypatch.setattr("agentbot_windows.native.time.sleep", lambda _: None)
    reported, proposals = [], []

    async def observe():
        return desktop.read("observe")

    async def planner(operation, **kwargs):
        if operation == "prompt": return {"role": "AppAgent", "messages": []}
        if operation == "result": reported.append(kwargs["result"])
        if operation == "response":
            if reported: return {"finished": True, "text": "Message is visible"}
            return {"action": {
                "function": "click_input", "observation_id": "observation-before",
                "window_id": "10", "control_id": "2", "arguments": {},
            }}
        return {}

    async def execute_action(engine, name, action, detail, execute):
        proposals.append(name)
        yield await execute()

    execution = AsyncMock(return_value={"ok": True, "effect_observed": False, "text": "Click dispatched"})
    adapter = UfoAgentAdapter(completion=AsyncMock(return_value="fixture"))
    await adapter.initialize(
        SimpleNamespace(observe=observe, planner=planner, execute_windows=execution),
        [], SimpleNamespace(execute_action=execute_action, emit_log=lambda *args: {}, context=RunContext()),
        model=SimpleNamespace(provider="openai", model="fixture"),
    )

    async def run():
        async for _ in adapter.execute_step("Send the draft"):
            pass

    if recovers:
        await run()
    else:
        with pytest.raises(RuntimeError, match="Previous input was not replayed"):
            await run()
    execution.assert_awaited_once()
    assert proposals == ["windows.click_input"]
    assert len(reported) == 1 and reported[0]["ok"]
    assert desktop.observe.call_count == (3 if recovers else 4)


@pytest.mark.parametrize("case", ["corrected", "denied", "limit"])
async def test_invalid_proposals_are_corrected_before_approval_and_never_restart_prior_actions(case):
    from agentbot.interfaces import ActionResult

    observations, approvals, reported = [], [], []
    response_count = 0

    async def observe():
        observations.append(f"observation-{len(observations)}")
        return {"observation_id": observations[-1]}

    async def planner(operation, **kwargs):
        nonlocal response_count
        if operation == "prompt": return {"role": "AppAgent", "messages": []}
        if operation == "result": reported.append(kwargs["result"])
        if operation == "response":
            stage = response_count
            response_count += 1
            if stage and (case == "limit" or stage == 1):
                return {"proposal_rejected": True, "text": "Use one bounded navigation key or shortcut"}
            if stage >= 4: return {"finished": True}
            return {"action": {
                "function": "type_text" if stage == 0 else "keyboard_input",
                "observation_id": observations[-1], "window_id": "10", "control_id": "2",
                "arguments": {"text": "Earlier draft"} if stage == 0 else {"keys": "^a" if stage == 2 else "{DELETE}"},
            }}
        return {}

    async def execute_action(engine, name, action, detail, execute):
        approvals.append(action)
        if case == "denied" and action["arguments"] == {"keys": "^a"}:
            yield ActionResult(False, "Denied", cancelled=True)
        else:
            yield await execute()

    execution = AsyncMock(return_value={"ok": True, "effect_observed": False, "text": "Input dispatched"})
    adapter = UfoAgentAdapter(completion=AsyncMock(return_value="fixture"))
    await adapter.initialize(
        SimpleNamespace(observe=observe, planner=planner, execute_windows=execution),
        [], SimpleNamespace(execute_action=execute_action, emit_log=lambda *args: {}, context=RunContext()),
        model=SimpleNamespace(provider="openai", model="fixture"),
    )

    async def run():
        async for _ in adapter.execute_step("Correct the draft"):
            pass

    if case == "limit":
        with pytest.raises(RuntimeError, match="three invalid action proposals"):
            await run()
        assert response_count == 4  # One completed action, then three invalid proposals.
    else:
        await run()
    assert execution.await_count == (3 if case == "corrected" else 1)
    assert approvals[0]["arguments"] == {"text": "Earlier draft"}
    assert [item["arguments"] for item in approvals[1:]] == (
        [{"keys": "^a"}, {"keys": "{DELETE}"}] if case == "corrected" else [{"keys": "^a"}] if case == "denied" else []
    )
    assert len(reported) == len(approvals)
    assert len({item["observation_id"] for item in approvals}) == len(approvals)
