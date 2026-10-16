import time

import pytest
from agentbot_macos.actions import MacAction, Permit
from agentbot_macos.protocol import Hello
from agentbot_macos.receipts import ReceiptJournal
from agentbot_macos.taskstar import TaskAssignment
from pydantic import ValidationError


def action(**changes):
    return MacAction.model_validate(
        {
            "function": "type_text",
            "observation_id": "observe-test",
            "window_id": "1",
            "control_id": "2",
            "arguments": {"text": "héllo 😀 {ENTER}"},
            **changes,
        }
    )


def hello():
    return Hello(
        device_id="mac-test",
        epoch="epoch-test",
        console_session="501:1",
        name="Test Mac",
        revision=1,
        sharing=True,
        armed=True,
        ready=True,
        screen_recording=True,
        accessibility=True,
    )


def permit():
    h = hello()
    return Permit(
        action_id="action-test",
        run_id="run-test-123",
        session_id="session-test",
        device_id=h.device_id,
        console_session=h.console_session,
        generation=1,
        epoch=h.epoch,
        local_revision=h.revision,
        expires_at=time.time() + 8,
        action=action(),
    ).sign("test-secret")


@pytest.mark.parametrize(
    "changes",
    [
        {"function": "getattr"},
        {"arguments": {"text": "line\nbreak"}},
        {"function": "key_input", "arguments": {"keys": ["command", "a", "enter"]}},
        {"function": "click", "control_id": "", "arguments": {"x": float("nan"), "y": 0.5}},
        {"function": "click", "arguments": {"x": 0.3, "y": 1.1}},
        {"function": "launch_app", "arguments": {"bundle_id": "/bin/sh"}},
        {"function": "type_text", "arguments": {"text": "hello", "fallback": "paste"}},
        {"function": "wait", "arguments": {"seconds": 31}},
        {
            "function": "drag",
            "arguments": {"x": 0.1, "y": 0.2, "to_x": 0.3, "to_y": 0.4, "duration": 60},
        },
    ],
)
def test_rejects_unsafe_or_malformed_operations(changes):
    with pytest.raises(ValidationError):
        action(**changes)


def test_permit_binds_exact_arguments_and_consent():
    p = permit()
    p.verify("test-secret", hello())
    for h in [
        hello().model_copy(update={"revision": 2}),
        hello().model_copy(update={"epoch": "new-epoch"}),
        hello().model_copy(update={"armed": False}),
        hello().model_copy(update={"device_id": "another"}),
    ]:
        with pytest.raises(ValueError):
            p.verify("test-secret", h)
    p.action.arguments["text"] = "changed"
    with pytest.raises(ValueError):
        p.verify("test-secret", hello())


def test_claim_crash_and_receipt_replay(tmp_path):
    path = tmp_path / "receipts.sqlite"
    p = permit()
    journal = ReceiptJournal(path)
    assert journal.claim(p) is None
    journal.close()
    journal = ReceiptJournal(path)
    assert journal.claim(p)["outcome_unknown"]
    changed = p.model_copy(deep=True)
    changed.action.arguments["text"] = "different"
    with pytest.raises(ValueError):
        journal.claim(changed)
    journal.finish(p.action_id, {"ok": True, "effect_observed": True})
    assert journal.claim(p) == {"ok": True, "effect_observed": True}
    journal.close()


def test_taskstar_is_bounded_data_not_code():
    task = TaskAssignment(task_id="task", device_id="mac", task_description="Type a draft")
    assert task.request_id == task.model_copy(update={"timeout": 5.0}).request_id
    for data in ({"object": object()}, {"deep": [[[[[[[[1]]]]]]]]}, {"too_big": "x" * 17000}):
        with pytest.raises((ValidationError, ValueError)):
            TaskAssignment(task_id="task", device_id="mac", task_description="test", task_data=data)
