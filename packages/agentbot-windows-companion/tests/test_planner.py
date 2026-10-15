import io
import json
import sys
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from agentbot_windows.planner import UfoPlanner
from agentbot_windows.protocol import WindowsAction


def response(keys):
    return json.dumps({"observation": "editor", "thought": "edit draft", "action": {
        "function": "keyboard_input", "arguments": {"keys": keys},
        "target": {"kind": "control", "id": "2", "name": "Editor"}, "status": "CONTINUE",
    }})


@pytest.fixture
def planner(monkeypatch):
    # Replace Windows-only UFO dependencies; use the real WindowsAction validator.
    def parsed(value):
        actions = value["action"]
        def action(item):
            return SimpleNamespace(**{**item, "target": SimpleNamespace(**item["target"])})
        return SimpleNamespace(action=[action(item) for item in actions] if isinstance(actions, list) else action(actions), comment="")
    monkeypatch.setitem(sys.modules, "ufo.agents.agent.basic", SimpleNamespace(BasicAgent=SimpleNamespace(response_to_dict=json.loads)))
    monkeypatch.setitem(sys.modules, "ufo.agents.agent.app_agent", SimpleNamespace(AppAgent=Mock()))
    monkeypatch.setitem(sys.modules, "ufo.agents.processors.schemas.response_schema", SimpleNamespace(
        AppAgentResponse=SimpleNamespace(model_validate=parsed), HostAgentResponse=Mock(),
    ))
    instance = UfoPlanner.__new__(UfoPlanner)
    instance.role, instance.selected = "AppAgent", "10"
    instance.request = instance.subtask = "Correct the draft"
    instance.plan = []
    instance.history = [{"action": "type_text", "result": {"ok": True, "text": "Draft inserted"}}]
    instance.last_action = WindowsAction(function="type_text", observation_id="observation-old", window_id="10", control_id="2", arguments={"text": "Draft"})
    instance.validation_feedback = ""
    instance.observation = {"observation_id": "observation-current", "window_id": "10", "windows": [{"id": "10", "name": "Fixture"}], "controls": []}
    instance.app = SimpleNamespace(message_constructor=lambda **kwargs: [{"role": "system", "content": "UFO prompt"}])
    return instance


@pytest.mark.parametrize("keys", ["^a{DELETE}", "^a^s", "{ENTER 100}", "{VK_CONTROL down}", "private-invalid-text"])
def test_invalid_keyboard_proposal_returns_feedback_without_changing_completed_history(planner, keys):
    history, previous = deepcopy(planner.history), planner.last_action
    result = planner.response(response(keys))
    assert result["proposal_rejected"] and "action" not in result
    assert keys not in result["text"]  # No raw input values in validation feedback.
    assert planner.history == history and planner.last_action is previous
    prompt = planner.prompt(planner.observation)["messages"][0]["content"]
    assert "last proposal was rejected before approval or input" in prompt
    assert result["text"] in prompt and "Draft inserted" in prompt


def test_combined_shortcut_is_corrected_as_separate_observed_proposals(planner):
    assert planner.response(response("^a{DELETE}"))["proposal_rejected"]
    proposals = []
    for index, keys in enumerate(["^a", "{DELETE}"]):
        planner.prompt({**planner.observation, "observation_id": f"observation-corrected-{index}"})
        proposal = planner.response(response(keys))
        assert proposal["action"]["arguments"] == {"keys": keys}
        assert proposal["action"]["observation_id"] == f"observation-corrected-{index}"
        proposals.append(proposal)
        planner.result({"ok": True, "text": "Key dispatched"})
    assert len(proposals) == 2 and not planner.validation_feedback
    assert [item["action"] for item in planner.history] == ["type_text", "keyboard_input", "keyboard_input"]


def test_action_batches_and_unsupported_functions_are_rejected(planner):
    raw = json.loads(response("^a"))
    raw["action"] = [raw["action"], raw["action"]]
    assert planner.response(json.dumps(raw))["proposal_rejected"]
    raw["action"] = {**raw["action"][0], "function": "shell"}
    assert planner.response(json.dumps(raw))["proposal_rejected"]


def test_unparseable_response_is_correctable_without_echoing_input(planner):
    result = planner.response("private broken JSON {")
    assert result["proposal_rejected"] and "private" not in result["text"]


def test_internal_planner_failure_is_not_treated_as_a_model_correction(planner):
    planner._response = Mock(side_effect=RuntimeError("Planner unavailable"))
    with pytest.raises(RuntimeError, match="Planner unavailable"):
        planner.response(response("^a"))


def test_worker_keeps_the_planner_after_invalid_proposal(planner, monkeypatch, tmp_path):
    from agentbot_windows import worker

    constructor = Mock(return_value=planner)
    monkeypatch.setattr("agentbot_windows.planner.UfoPlanner", constructor)
    monkeypatch.setattr(worker, "qualify_source", lambda path: path)
    monkeypatch.setattr(worker.logging, "disable", lambda _: None)
    monkeypatch.setattr(sys, "path", list(sys.path))
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["worker", "--source", str(tmp_path), "--kind", "planner"])
    commands = [
        {"operation": "start", "request": "Correct the draft"},
        {"operation": "response", "response": response("^a{DELETE}")},
        {"operation": "response", "response": response("^a")},
    ]
    monkeypatch.setattr(sys, "stdin", io.StringIO("\n".join(json.dumps({"method": "planner", "arguments": cmd}) for cmd in commands) + "\n"))
    output = io.StringIO()
    monkeypatch.setattr(sys, "stdout", output)
    worker.main()
    answers = [json.loads(line) for line in output.getvalue().splitlines()]
    assert all("error" not in answer for answer in answers)
    assert answers[1]["result"]["proposal_rejected"]
    assert answers[2]["result"]["action"]["arguments"] == {"keys": "^a"}
    constructor.assert_called_once()
