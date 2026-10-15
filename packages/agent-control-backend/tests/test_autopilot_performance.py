import asyncio

import pytest
from approvals_support import application as application
from approvals_support import bot_for as bot_for
from approvals_support import finished as finished
from approvals_support import pending as pending
from autopilot_support import toggle as toggle
from fakes import FakeSandbox
from fastapi.testclient import TestClient
from runtime_support import decide as decide
from runtime_support import start as start
from workspace_services_support import create_computer as create_computer
from workspace_services_support import live_app as live_app


@pytest.mark.parametrize("autopilot,reads", [(True, 2), (False, 4)])
def test_revision_reads_decrease_only_for_immediate_autopilot(
    tmp_path, monkeypatch, autopilot, reads
):
    app, manager, _ = application(tmp_path)
    calls = []
    original = FakeSandbox.workspace_revision

    async def revision(self):
        calls.append(self)
        return await original(self)

    monkeypatch.setattr(FakeSandbox, "workspace_revision", revision)
    with TestClient(app) as client:
        bid = bot_for(client)
        if autopilot:
            toggle(client, bid)
        start(client, bid, prompt="echo hi")
        if not autopilot:
            decide(client, bid, pending(client, bid)["id"])
        state = finished(client, bid)
        assert state["actions"][0]["status"] == "completed"
        assert len(calls) == reads
        metrics = [event["data"] for event in state["events"] if event["type"] == "run.metrics"]
        action = next(metric for metric in metrics if metric["category"] == "action.timing")
        assert action["context_reads"] == (1 if autopilot else 2)
        assert action["execution_ms"] >= 0 and action["context_check_ms"] >= 0
        assert any(metric["category"] == "event.persistence" for metric in metrics)


def test_checked_command_still_rejects_workspace_change_before_execution(tmp_path, monkeypatch):
    app, manager, _ = application(tmp_path)
    original = FakeSandbox.run_command_checked

    async def changed(self, command, *, expected):
        self.files["/workspace/operator.txt"] = "operator edit"
        return await original(self, command, expected=expected)

    monkeypatch.setattr(FakeSandbox, "run_command_checked", changed)
    with TestClient(app) as client:
        bid = bot_for(client)
        toggle(client, bid)
        receipt = start(client, bid, prompt="echo hi").json()
        state = finished(client, bid)
        assert state["actions"][0]["status"] == "failed"
        assert not manager._cache[receipt["session_id"]].commands


def test_patch_does_not_overwrite_concurrent_operator_edit(tmp_path, monkeypatch):
    async def runner(tools, *args):
        await tools["mutate_file"]("a.txt", "original")
        return await tools["patch_file"]("a.txt", "original", "new")

    app, manager, _ = application(tmp_path, runner=runner)
    original = FakeSandbox.write_workspace_file_checked

    async def changed(self, path, content, *, expected):
        if content == "new":
            self.files["/workspace/a.txt"] = "operator edit"
        return await original(self, path, content, expected=expected)

    monkeypatch.setattr(FakeSandbox, "write_workspace_file_checked", changed)
    with TestClient(app) as client:
        bid = bot_for(client)
        toggle(client, bid)
        receipt = start(client, bid, prompt="repair the file").json()
        assert finished(client, bid)["actions"][-1]["status"] == "failed"
        assert manager._cache[receipt["session_id"]].files["/workspace/a.txt"] == "operator edit"


def test_health_inspections_share_work_and_do_not_leak_caller_mutations(tmp_path):
    app, manager = live_app(tmp_path)
    calls = []
    original = manager.inspect

    async def inspect(sid):
        calls.append(sid)
        await asyncio.sleep(0.01)
        return await original(sid)

    manager.inspect = inspect
    with TestClient(app) as client:
        bid = bot_for(client)
        computer = create_computer(client, bid)
        service = app.state.runtime.computers
        service._inspections.clear()
        calls.clear()

        async def observe_together():
            return await asyncio.gather(service.observe(bid), service.observe(bid))

        first, second = client.portal.call(observe_together)
        assert len(calls) == 1
        first["capabilities"]["capture"] = False
        assert second["capabilities"]["capture"] is True
        again = client.portal.call(service.observe, bid)
        assert again["observed_at"] == second["observed_at"] and len(calls) == 1
        events = app.state.runtime.store.snapshot(bid)["events"]
        assert (
            sum(
                event["type"] == "computer.health"
                and event["data"]["observed_at"] == second["observed_at"]
                for event in events
            )
            == 1
        )
        # A lifecycle transition invalidates the cached report immediately.
        app.state.runtime.store.set_computer(bid, computer["id"], "closed")
        assert client.portal.call(service.observe, bid)["lifecycle"] == "closed"


def test_metrics_failure_does_not_break_action_cleanup(tmp_path, monkeypatch):
    app, manager, _ = application(tmp_path)
    store = app.state.runtime.store
    original = store._event

    def event(db, bid, kind, *args):
        if kind == "run.metrics":
            raise RuntimeError("diagnostic sink unavailable")
        return original(db, bid, kind, *args)

    monkeypatch.setattr(store, "_event", event)
    with TestClient(app) as client:
        bid = bot_for(client)
        toggle(client, bid)
        receipt = start(client, bid, prompt="echo hi").json()
        state = finished(client, bid)
        assert state["run"]["status"] == "completed"
        assert state["actions"][0]["status"] == "completed"
        assert not state["pending_approvals"]
        assert manager._cache[receipt["session_id"]].commands == ["echo hi"]


@pytest.mark.parametrize(
    "status,source,checked,revision",
    [
        ("pending", "autopilot", True, "original"),
        ("approved", "manual", True, "original"),
        ("approved", "policy", True, "original"),
        ("approved", "autopilot", False, "original"),
        ("approved", "autopilot", True, None),
    ],
)
async def test_context_recheck_is_retained_outside_eligible_path(status, source, checked, revision):
    from types import SimpleNamespace

    from agentbot_control.approvals import ActionArbiter

    sandbox = FakeSandbox()
    if not checked:
        sandbox.run_command_checked = None
    arbiter = ActionArbiter(None, None, SimpleNamespace(sandbox=sandbox), None)

    async def observe(*args):
        return {"workspace_revision": "observed again"}

    arbiter.context = observe
    latest, rechecked = await arbiter.dispatch_context(
        "bash",
        {"command": "echo hi"},
        {"workspace_revision": revision},
        {"status": status, "decision_source": source},
    )
    assert rechecked and latest == {"workspace_revision": "observed again"}


async def test_disconnected_health_observer_does_not_cancel_shared_inspection():
    from types import SimpleNamespace

    from agentbot_control.computer import Computers

    started, release = asyncio.Event(), asyncio.Event()
    calls = []

    async def inspect(sid):
        calls.append(sid)
        started.set()
        await release.wait()
        return {"provider": "docker", "compatible": True}

    service = Computers(
        None,
        SimpleNamespace(sandboxes=SimpleNamespace(inspect=inspect)),
        cloud=None,
        lifecycle=None,
        control=None,
        toolkit=None,
        bind=None,
        action_locks=None,
        workspace_features=True,
        ensure=None,
        workspaces=None,
    )
    first = asyncio.create_task(service._inspect({"id": "computer1"}))
    await started.wait()
    second = asyncio.create_task(service._inspect({"id": "computer1"}))
    await asyncio.sleep(0)
    first.cancel()
    with pytest.raises(asyncio.CancelledError):
        await first
    release.set()
    assert (await second)["compatible"]
    assert calls == ["computer1"] and not service._inspecting
    await service.shutdown()
