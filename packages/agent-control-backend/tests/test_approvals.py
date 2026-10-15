"""B2 integration tests use real adapters and a deterministic model/sandbox."""

from concurrent.futures import ThreadPoolExecutor

import pytest
from agentbot.interfaces import CommandResult
from approvals_support import application as application
from approvals_support import bot_for as bot_for
from approvals_support import finished as finished
from approvals_support import pending as pending
from approvals_support import save_rule as save_rule
from control_support import _app as _app
from control_support import _create_bot as _create_bot
from control_support import _key as _key
from control_support import _register as _register
from fastapi.testclient import TestClient
from runtime_support import decide as decide
from runtime_support import start as start
from runtime_support import wait_state as wait_state


@pytest.mark.parametrize("framework", ["microsoft", "anthropic"])
@pytest.mark.parametrize("exit_code,timed_out", [(0, False), (7, False), (124, True)])
def test_both_adapters_correlate_real_outcomes(tmp_path, framework, exit_code, timed_out):
    app, sandboxes, models = application(tmp_path, framework)
    with TestClient(app) as client:
        bot = bot_for(client, framework)
        receipt = start(client, bot, prompt="do work").json()
        approval = pending(client, bot)
        sandbox = sandboxes._cache[receipt["session_id"]]

        async def run_command(command):
            sandbox.commands.append(command)
            return CommandResult(
                "command_test",
                exit_code,
                stdout="out",
                stderr="err",
                timed_out=timed_out,
                stdout_truncated=True,
            )

        sandbox.run_command = run_command
        assert decide(client, bot, approval["id"]).json()["accepted"]
        state = finished(client, bot)
        events = state["events"]
        names = [event["type"] for event in events]
        outcome = next(
            event for event in events if event["type"] in {"action.completed", "action.failed"}
        )
        assert (
            names.index("approval.resolved")
            < names.index("action.started")
            < names.index(outcome["type"])
        )
        assert outcome["action_id"] == approval["action_id"]
        assert outcome["run_id"] == receipt["run_id"]
        assert outcome["data"]["command_id"] == "command_test"
        assert outcome["data"]["exit_code"] == exit_code
        assert outcome["data"]["timed_out"] == timed_out
        assert outcome["data"]["stdout_truncated"] is True
        assert outcome["data"]["ok"] == (exit_code == 0)
        assert outcome["data"]["started_at"] <= outcome["data"]["ended_at"]
        assert events[-1]["data"]["failed_actions"] == (0 if exit_code == 0 else 1)
        assert sandbox.commands == ["do work"]
        if framework == "anthropic":
            assert models[0].calls[1][-1]["content"][0].get("is_error", False) == (exit_code != 0)


def test_exact_policy_applies_without_socket_and_revocation_restores_approval(tmp_path):
    app, sandboxes, _ = application(tmp_path)
    with TestClient(app) as client:
        bot = bot_for(client)
        receipt = start(client, bot, prompt="python report.py").json()
        approval = pending(client, bot)
        policy = save_rule(client, bot, approval)
        assert policy.status_code == 201, policy.text
        assert save_rule(client, bot, approval).json() == policy.json()
        assert "workspace revision" in policy.json()["summary"]
        decide(client, bot, approval["id"])
        finished(client, bot)
        start(client, bot, request="second_run_request", prompt="python report.py")
        state = finished(client, bot)
        assert state["pending_approvals"] == []
        resolved = [event for event in state["events"] if event["type"] == "approval.resolved"][-1]
        assert resolved["data"]["policy_id"] == policy.json()["id"]
        assert resolved["data"]["policy_version"] == 1
        assert resolved["data"]["decided_by"].startswith("policy:")
        revoke = client.post(
            f"/api/bots/{bot}/approval-policies/{policy.json()['id']}/revoke",
            json={"request_id": "revoke_request"},
        )
        assert revoke.json()["status"] == "revoked" and revoke.json()["version"] == 2
        start(client, bot, request="third_run_request", prompt="python report.py")
        assert pending(client, bot)["status"] == "pending"
        assert sandboxes._cache[receipt["session_id"]].commands == ["python report.py"] * 2


@pytest.mark.parametrize("change", ["arguments", "script"])
def test_argument_and_script_changes_invalidate_saved_rule(tmp_path, change):
    app, sandboxes, _ = application(tmp_path)
    with TestClient(app) as client:
        bot = bot_for(client)
        receipt = start(client, bot, prompt="python report.py").json()
        approval = pending(client, bot)
        assert save_rule(client, bot, approval).status_code == 201
        decide(client, bot, approval["id"])
        finished(client, bot)
        sandbox = sandboxes._cache[receipt["session_id"]]
        if change == "script":
            sandbox.files["/workspace/report.py"] = "new script"
        prompt = "python report.py --publish" if change == "arguments" else "python report.py"
        start(client, bot, request="changed_run_request", prompt=prompt)
        assert pending(client, bot)["status"] == "pending"
        assert len(sandbox.commands) == 1


def test_pending_context_change_prevents_dispatch(tmp_path):
    app, sandboxes, _ = application(tmp_path)
    with TestClient(app) as client:
        bot = bot_for(client)
        receipt = start(client, bot, prompt="python report.py").json()
        approval = pending(client, bot)
        sandbox = sandboxes._cache[receipt["session_id"]]
        sandbox.files["/workspace/report.py"] = "changed while reviewing"
        result = decide(client, bot, approval["id"]).json()
        assert not result["accepted"] and result["status"] == "cancelled"
        state = finished(client, bot)
        assert not sandbox.commands
        assert not any(event["type"] == "action.started" for event in state["events"])
        assert any(
            event["type"] == "action.failed" and event["data"]["cancelled"]
            for event in state["events"]
        )


def test_duplicate_conflicting_and_stale_revision_decisions(tmp_path):
    app, sandboxes, _ = application(tmp_path)
    with TestClient(app) as client:
        bot = bot_for(client)
        receipt = start(client, bot).json()
        approval = pending(client, bot)
        url = f"/api/bots/{bot}/approvals/{approval['id']}/decision"
        stale = client.post(
            url,
            json={"request_id": "stale_revision", "decision": "approve", "revision": 8},
        )
        assert stale.json()["status"] == "pending" and stale.json()["accepted"] is False
        with ThreadPoolExecutor(2) as pool:
            responses = list(
                pool.map(
                    lambda n: decide(client, bot, approval["id"], f"decision_request_{n}").json(),
                    range(2),
                )
            )
        assert responses[0] == responses[1]
        conflicting = client.post(
            url,
            json={
                "request_id": "deny_after_approved",
                "decision": "deny",
                "revision": 1,
            },
        )
        assert (
            conflicting.json()["status"] == "approved" and conflicting.json()["accepted"] is False
        )
        finished(client, bot)
        assert len(sandboxes._cache[receipt["session_id"]].commands) == 1
        with app.state.runtime.store.transaction() as db:
            row = db.execute(
                "SELECT * FROM actions WHERE id=?", (approval["action_id"],)
            ).fetchone()
            assert "hello" not in row["arguments_sealed"]
            assert app.state.runtime.policies.open(row["arguments_sealed"]) == {
                "command": "echo hello"
            }


def test_timeout_decision_race_has_one_winner(tmp_path):
    app, sandboxes, _ = application(tmp_path)
    with TestClient(app) as client:
        bot = bot_for(client)
        receipt = start(client, bot).json()
        approval = pending(client, bot)
        service = app.state.runtime.approvals
        with ThreadPoolExecutor(2) as pool:
            decisions = [
                pool.submit(decide, client, bot, approval["id"]),
                pool.submit(service.expire, approval["id"], force=True),
            ]
            for result in decisions:
                result.result()
        # An explicit stale HTTP decision also wakes any waiting adapter after timeout won.
        decision = decide(client, bot, approval["id"], "after_race_request").json()
        state = finished(client, bot)
        resolved = [event for event in state["events"] if event["type"] == "approval.resolved"]
        assert len(resolved) == 1
        assert len(sandboxes._cache[receipt["session_id"]].commands) == (
            decision["status"] == "approved"
        )


def test_real_deadline_expires_without_observer(tmp_path):
    app, sandboxes, _ = application(tmp_path)
    app.state.runtime.approval_timeout = 0.1
    with TestClient(app) as client:
        bot = bot_for(client)
        receipt = start(client, bot).json()
        state = finished(client, bot)
        required = next(event for event in state["events"] if event["type"] == "approval.required")
        assert decide(client, bot, required["data"]["approval_id"]).json()["status"] == "expired"
        assert not sandboxes._cache[receipt["session_id"]].commands


def test_generation_stop_and_foreign_ids_cannot_authorize(tmp_path):
    app, sandboxes, _ = application(tmp_path)
    with TestClient(app) as client, TestClient(app) as foreign:
        bot = bot_for(client)
        _register(foreign, "other_user")
        receipt = start(client, bot).json()
        approval = pending(client, bot)
        assert decide(foreign, bot, approval["id"]).status_code == 404
        assert save_rule(foreign, bot, approval).status_code == 404
        assert foreign.get(f"/api/bots/{bot}/approval-policies").status_code == 404
        with app.state.runtime.store.transaction() as db:
            db.execute(
                "UPDATE computer_sessions SET generation=generation+1 WHERE id=?",
                (receipt["session_id"],),
            )
        assert decide(client, bot, approval["id"]).json()["status"] == "cancelled"
        finished(client, bot)
        assert not sandboxes._cache[receipt["session_id"]].commands
        receipt = start(client, bot, request="stop_run_request").json()
        approval = pending(client, bot)
        client.post(
            f"/api/bots/{bot}/runs/{receipt['run_id']}/stop",
            json={"request_id": "stop_pending_request"},
        )
        assert (
            decide(client, bot, approval["id"], "decide_after_stop").json()["status"] == "cancelled"
        )


def test_file_rule_pins_content_and_revision(tmp_path):
    async def runner(tools, prompt, context, on_text):
        return await tools["mutate_file"]("result.txt", prompt)

    app, sandboxes, _ = application(tmp_path, runner=runner)
    with TestClient(app) as client:
        bot = bot_for(client)
        receipt = start(client, bot, prompt="first").json()
        approval = pending(client, bot)
        assert "first" in approval["detail"]
        assert save_rule(client, bot, approval).status_code == 201
        decide(client, bot, approval["id"])
        finished(client, bot)
        start(client, bot, request="overwrite_request", prompt="second")
        assert pending(client, bot)["status"] == "pending"
        assert sandboxes._cache[receipt["session_id"]].files["/workspace/result.txt"] == "first"


def test_model_error_does_not_fabricate_action_success(tmp_path):
    async def runner(tools, prompt, context, on_text):
        raise RuntimeError("model unavailable")

    app, _, _ = application(tmp_path, runner=runner)
    with TestClient(app) as client:
        bot = bot_for(client)
        start(client, bot)
        state = finished(client, bot)
        assert state["run"]["status"] == "failed"
        assert not any(event["type"].startswith("action.") for event in state["events"])


@pytest.mark.parametrize("invalidate", ["revocation", "expiry"])
def test_policy_is_rechecked_at_dispatch(tmp_path, invalidate):
    app, sandboxes, _ = application(tmp_path)
    with TestClient(app) as client:
        bot = bot_for(client)
        receipt = start(client, bot, prompt="same command").json()
        approval = pending(client, bot)
        policy = save_rule(client, bot, approval).json()
        decide(client, bot, approval["id"])
        finished(client, bot)
        service = app.state.runtime.approvals
        original = service.claim

        def invalidate_then_claim(aid, arguments, context):
            with app.state.runtime.store.transaction() as db:
                if invalidate == "revocation":
                    db.execute(
                        "UPDATE approval_policies SET revoked_at='2026-01-01',version=version+1 WHERE id=?",
                        (policy["id"],),
                    )
                else:
                    db.execute(
                        "UPDATE approval_policies SET expires_at='2026-01-01' WHERE id=?",
                        (policy["id"],),
                    )
            return original(aid, arguments, context)

        service.claim = invalidate_then_claim
        start(client, bot, request="policy_race_run", prompt="same command")
        state = finished(client, bot)
        assert sandboxes._cache[receipt["session_id"]].commands == ["same command"]
        latest = [event for event in state["events"] if event["run_id"] == state["run"]["id"]]
        assert not any(event["type"] == "action.started" for event in latest)
        assert any(
            event["type"] == "action.failed" and event["data"]["cancelled"] for event in latest
        )


def test_browser_rule_has_exact_origin_and_scope_cannot_be_substituted(tmp_path):
    async def runner(tools, prompt, context, on_text):
        return await tools["open_browser"](prompt)

    app, sandboxes, _ = application(tmp_path, runner=runner)
    with TestClient(app) as client:
        bot = bot_for(client)
        receipt = start(client, bot, prompt="https://example.test/start").json()
        approval = pending(client, bot)
        assert save_rule(client, bot, approval).status_code == 201
        rejected = client.post(
            f"/api/bots/{bot}/approval-policies",
            json={
                "request_id": "tampered_scope_request",
                "approval_id": approval["id"],
                "operation": "bash",
                "constraints": {"command": ".*"},
            },
        )
        assert rejected.status_code == 422
        decide(client, bot, approval["id"])
        finished(client, bot)
        start(
            client,
            bot,
            request="same_origin_request",
            prompt="https://example.test/another",
        )
        finished(client, bot)
        start(
            client,
            bot,
            request="another_origin_request",
            prompt="https://example.test.evil/another",
        )
        assert pending(client, bot)["status"] == "pending"
        assert sandboxes._cache[receipt["session_id"]].opened == [
            "https://example.test/start",
            "https://example.test/another",
        ]


def test_current_actions_and_explicit_plan_survive_event_retention(tmp_path):
    app, _, _ = application(tmp_path)
    with TestClient(app) as client:
        bot = bot_for(client)
        receipt = start(client, bot, prompt="echo report").json()
        approval = pending(client, bot)
        decide(client, bot, approval["id"])
        finished(client, bot)
        from agentbot.events import RealTimeEventStreamer

        store = app.state.runtime.store
        plan = RealTimeEventStreamer().emit_plan(
            "test", [{"id": "verify", "title": "Verify output", "status": "completed"}]
        )
        store.record_frame(bot, receipt["run_id"], plan)
        with store.transaction() as db:
            db.execute("DELETE FROM bot_events WHERE bot_id=?", (bot,))
        state = client.get(f"/api/bots/{bot}/snapshot").json()
        assert state["events"] == []
        assert state["actions"][0]["status"] == "completed"
        assert state["actions"][0]["result"]["exit_code"] == 0
        assert state["plan"][0]["id"] == "verify"
        assert "arguments_sealed" not in state["actions"][0]
