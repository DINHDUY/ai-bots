"""B2 integration tests use real adapters and a deterministic model/sandbox."""

from agentbot.adapters.anthropic import ClaudeAgentAdapter, ModelTurn, ToolUse
from agentbot.adapters.microsoft import MicrosoftAgentAdapter
from control_support import _app, _create_bot, _key, _register
from runtime_support import wait_state


def application(tmp_path, framework="microsoft", runner=None):
    app, sandboxes, _, _ = _app(tmp_path)
    clients = []

    async def default_runner(tools, prompt, context, on_text):
        return await tools["run_terminal_command"](prompt)

    class Model:
        def __init__(self):
            self.calls = []

        async def complete(self, *, messages, system):
            self.calls.append(messages)
            if len(self.calls) == 1:
                prompt = messages[-1]["content"][0]["text"]
                return ModelTurn("tool_use", "", [ToolUse("t1", "bash", None, {"command": prompt})])
            return ModelTurn("end_turn", "Finished turn")

    def adapter():
        if framework == "microsoft":
            return MicrosoftAgentAdapter(runner=runner or default_runner)
        model = Model()
        clients.append(model)
        return ClaudeAgentAdapter(client=model)

    app.state.runtime.kernel.registry.register_framework(framework, adapter)
    return app, sandboxes, clients


def bot_for(client, framework="microsoft"):
    _register(client)
    key = _key(client, "anthropic" if framework == "anthropic" else "openai")
    return _create_bot(client, framework=framework, credential_id=key["id"]).json()["id"]


def pending(client, bot):
    return wait_state(client, bot, lambda s: bool(s["pending_approvals"]))["pending_approvals"][0]


def finished(client, bot):
    return wait_state(
        client,
        bot,
        lambda s: (
            s["run"]["status"] not in {"preparing", "running", "awaiting_approval", "stopping"}
        ),
    )


def save_rule(client, bot, approval, request="save_policy_request"):
    return client.post(
        f"/api/bots/{bot}/approval-policies",
        json={
            "request_id": request,
            "approval_id": approval["id"],
            "ttl_seconds": 3600,
        },
    )
