"""Imported bots execute approved tools on one real workspace Docker computer."""

import pytest
from agentbot.adapters.microsoft import MicrosoftAgentAdapter
from agentbot.sandbox.docker import DockerSessionManager
from control_support import _app, _register
from fastapi.testclient import TestClient
from runtime_support import decide, start, wait_state
from workflow_import_support import draft, imported

pytestmark = pytest.mark.docker


def test_imported_bots_share_files_approvals_and_human_control(tmp_path):
    import docker

    app, _, _, _ = _app(tmp_path)
    manager = DockerSessionManager(client=docker.from_env())
    manager.configure_scope("control", app.state.runtime.store.deployment)
    app.state.kernel.sandboxes = manager
    outputs = []

    async def runner(tools, prompt, context, on_text):
        command = (
            "printf shared-data > /workspace/import-shared.txt"
            if "write" in prompt
            else "cat /workspace/import-shared.txt"
        )
        output = await tools["run_terminal_command"](command)
        outputs.append(output)
        return str(output)

    app.state.kernel.registry.register_framework(
        "microsoft", lambda: MicrosoftAgentAdapter(runner=runner)
    )
    with TestClient(app) as client:
        _register(client)
        result = imported(client, draft(client, count=2))
        wid = result["workspace_id"]
        first, second = [bot["bot_id"] for bot in result["bots"]]
        created = client.post(
            f"/api/workspaces/{wid}/computer/lifecycle",
            json={
                "request_id": "import_computer_create",
                "operation": "create",
                "generation": 0,
            },
        )
        assert created.status_code == 200, created.text
        computer = created.json()["computer"]
        sid = computer["id"]
        try:
            refused = client.delete(f"/api/bots/{first}")
            assert refused.status_code == 409 and refused.json()["code"] == "computer_busy"
            assert client.get(f"/api/bots/{first}/collaboration").json()["state"] == "enabled"
            for index, (bid, prompt) in enumerate(
                ((first, "write shared file"), (second, "read shared file"))
            ):
                accepted = start(client, bid, f"import_run_{index}", prompt)
                assert accepted.status_code == 202, accepted.text
                assert accepted.json()["session_id"] == sid
                state = wait_state(client, bid, lambda s: s["pending_approvals"])
                assert (
                    decide(
                        client, bid, state["pending_approvals"][0]["id"], f"import_approve_{index}"
                    ).status_code
                    == 200
                )
                wait_state(client, bid, lambda s: s["run"]["status"] == "completed")
            assert "shared-data" in str(outputs[-1])
            lease = client.post(
                f"/api/bots/{first}/sessions/{sid}/control/acquire",
                json={
                    "request_id": "import_human_control",
                    "client_id": "import_browser",
                    "generation": computer["generation"],
                    "surface": "browser",
                },
            )
            assert lease.status_code == 200, lease.text
            for index, bid in enumerate((first, second)):
                blocked = start(client, bid, f"import_paused_{index}")
                assert blocked.status_code == 409 and blocked.json()["code"] == "human_control"
                snapshot = client.get(f"/api/bots/{bid}/snapshot").json()
                assert (
                    snapshot["computer"]["id"] == sid
                    and snapshot["computer"]["scope"] == "workspace"
                )
            with app.state.runtime.store.transaction() as db:
                assert db.execute("SELECT COUNT(*) FROM computer_sessions").fetchone()[0] == 1
        finally:
            # Test-owned container only; leave existing application services intact.
            client.portal.call(manager.close, sid)
