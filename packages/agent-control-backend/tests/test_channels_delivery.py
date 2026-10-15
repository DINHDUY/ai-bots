from agentbot.adapters.microsoft import MicrosoftAgentAdapter
from channels_support import post as post
from channels_support import settled as settled
from channels_support import setup as setup
from control_support import _app as _app
from control_support import _create_bot as _create_bot
from control_support import _key as _key
from control_support import _register as _register
from fastapi.testclient import TestClient


def test_computer_work_waits_and_cancel_never_provisions(tmp_path):
    app, sandboxes, _, _ = _app(tmp_path)
    with TestClient(app) as client:
        wid, bots = setup(client)
        message = post(client, wid, bots[0], requires_computer=True)
        state = settled(client, wid, lambda s: s["deliveries"][0]["state"] == "blocked")
        assert state["deliveries"][0]["reason"] == "waiting_for_computer"
        assert (
            client.post(
                f"/api/workspaces/{wid}/channel/threads/{message['thread_id']}/cancel"
            ).status_code
            == 200
        )
        assert (
            client.get(f"/api/workspaces/{wid}/channel").json()["deliveries"][0]["state"]
            == "cancelled"
        )
        assert sandboxes.created == 0


def test_settings_are_atomic_and_opt_out_survives_restart(tmp_path):
    app, _, _, _ = _app(tmp_path)
    with TestClient(app) as client:
        _wid, bots = setup(client)
        bid = bots[0]
        saved = client.get(f"/api/bots/{bid}/collaboration").json()
        tools = client.get(f"/api/bots/{bid}/tools").json()
        payload = {
            "name": "Changed",
            "tool_selection": [],
            "expected_tools_revision": tools["tools_revision"],
            "collaboration": {
                "revision": saved["revision"] - 1,
                "enabled": False,
                "purpose": "My public role",
            },
        }
        assert client.patch(f"/api/bots/{bid}", json=payload).status_code == 409
        assert client.get(f"/api/bots/{bid}").json()["name"] == "Writer"
        assert (
            client.get(f"/api/bots/{bid}/tools").json()["tools_revision"] == tools["tools_revision"]
        )
        payload["collaboration"]["revision"] = saved["revision"]
        assert client.patch(f"/api/bots/{bid}", json=payload).status_code == 200
        assert client.get(f"/api/bots/{bid}/tools").json()["tool_selection"] == []
        assert client.get(f"/api/bots/{bid}/collaboration").json()["state"] == "disabled"
    restarted, _, _, _ = _app(tmp_path)
    with TestClient(restarted) as client:
        assert (
            client.post("/api/login", json={"username": "ada", "password": "password1"}).status_code
            == 200
        )
        assert client.get(f"/api/bots/{bid}/tools").json()["tool_selection"] == []
        assert client.get(f"/api/bots/{bid}/collaboration").json()["state"] == "disabled"


def test_explicit_creation_enrollment_and_legacy_empty_selection(tmp_path):
    app, _, _, _ = _app(tmp_path)
    from agentbot_control.tool_libraries import ToolLibraries

    with TestClient(app) as client:
        wid, _ = setup(client)
        config = client.get(f"/api/workspaces/{wid}/channel").json()
        assert (
            client.patch(
                f"/api/workspaces/{wid}/channel",
                json={
                    "revision": config["revision"],
                    "enabled": True,
                    "enroll_future": True,
                },
            ).status_code
            == 200
        )
        empty = _create_bot(client, name="Private", tool_selection=[]).json()
        assert client.get(f"/api/bots/{empty['id']}/collaboration").json()["published"] == 0
        joined = _create_bot(
            client,
            name="New peer",
            tool_selection=[ToolLibraries.item("workspace.messaging", "workspace_messaging")],
            join_workspace_channel=True,
        )
        assert joined.status_code == 201, joined.text
        directory = client.get(f"/api/workspaces/{wid}/bots/directory").json()
        assert "New peer" in {b["name"] for b in directory["bots"]}
        assert "Private" not in {b["name"] for b in directory["bots"]}
        assert (
            _create_bot(client, tool_selection=[], join_workspace_channel=True).status_code == 422
        )


def test_budget_rate_and_utf8_limits_do_not_partially_post(tmp_path):
    app, _, _, _ = _app(tmp_path)
    with TestClient(app) as client:
        wid, bots = setup(client)
        app.state.runtime.accepting = False
        message = post(client, wid, bots[0])
        with app.state.runtime.store.transaction() as db:
            db.execute(
                "UPDATE channel_threads SET runs_used=8 WHERE id=?",
                (message["thread_id"],),
            )
        response = client.post(
            f"/api/workspaces/{wid}/channel/messages",
            json={
                "request_id": "budget_request",
                "thread_id": message["thread_id"],
                "recipient_id": bots[1],
                "text": "Do more",
            },
        )
        assert response.status_code == 409
        response = client.post(
            f"/api/workspaces/{wid}/channel/messages",
            json={
                "request_id": "utf8_request",
                "recipient_id": bots[1],
                "text": "漢" * 3000,
            },
        )
        assert response.status_code == 409
        assert len(client.get(f"/api/workspaces/{wid}/channel/messages").json()["messages"]) == 1


def test_revoked_member_cannot_replay_a_message_or_keep_stream(tmp_path):
    app, _, _, _ = _app(tmp_path)
    with TestClient(app) as owner, TestClient(app) as operator:
        wid, bots = setup(owner)
        _register(operator, "operator")
        assert (
            owner.post(
                f"/api/workspaces/{wid}/members",
                json={"username": "operator", "role": "operator"},
            ).status_code
            == 200
        )
        response = owner.post(
            f"/api/bots/{bots[0]}/execution-grants",
            json={"username": "operator", "enabled": True},
        )
        assert response.status_code == 200, response.text
        app.state.runtime.accepting = False
        message = post(operator, wid, bots[0])
        with operator.websocket_connect(f"/api/workspaces/{wid}/channel/events/ws") as socket:
            assert socket.receive_json()["events"]
            assert (
                owner.post(
                    f"/api/workspaces/{wid}/members",
                    json={"username": "operator", "role": "remove"},
                ).status_code
                == 200
            )
            socket.send_text("poll")
            assert socket.receive()["type"] == "websocket.close"
        response = operator.post(
            f"/api/workspaces/{wid}/channel/messages",
            json={
                "request_id": "channel_test_request",
                "recipient_id": bots[0],
                "text": message["body"],
            },
        )
        assert response.status_code == 404


def test_restart_reconciles_receipt_without_repeating_an_unconfirmed_run(tmp_path):
    app, _, _, _ = _app(tmp_path)
    with TestClient(app) as client:
        wid, bots = setup(client)
        runtime = app.state.runtime
        runtime.accepting = False
        message = post(client, wid, bots[0])
        with runtime.store.transaction() as db:
            delivery = db.execute(
                "SELECT * FROM channel_deliveries WHERE message_id=?", (message["id"],)
            ).fetchone()
            bot = runtime.catalog.get_bot_by_id_tx(db, bots[0])
        admitted, _ = runtime.store.admit(
            bot,
            bot.owner_id,
            "channel_delivery_" + delivery["id"],
            "Crash boundary",
            "channel_request",
            run_mode="communication",
            channel_delivery_id=delivery["id"],
        )
        # Simulate a worker dying before delivery bookkeeping could be read by its poller.
        with runtime.store.transaction() as db:
            db.execute(
                "UPDATE channel_deliveries SET state='queued',run_id=NULL WHERE id=?",
                (delivery["id"],),
            )
    restarted, sandboxes, _, _ = _app(tmp_path)
    with TestClient(restarted) as client:
        client.post("/api/login", json={"username": "ada", "password": "password1"})
        state = settled(client, wid, lambda s: s["deliveries"][0]["state"] == "failed")
        assert state["deliveries"][0]["run_id"] == admitted["run_id"]
        with restarted.state.runtime.store.transaction() as db:
            assert db.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == 1
            assert not db.execute("PRAGMA foreign_key_check").fetchall()
        assert sandboxes.created == 0


def test_communication_can_yield_for_computer_without_starting_it(tmp_path):
    app, sandboxes, _, _ = _app(tmp_path)

    async def runner(tools, prompt, context, on_text):
        await tools["request_computer_work"](
            "Use the selected computer tools to inspect the requested file."
        )
        raise AssertionError("Yield must end this segment")

    app.state.kernel.registry.register_framework(
        "microsoft", lambda: MicrosoftAgentAdapter(runner=runner)
    )
    with TestClient(app) as client:
        wid, bots = setup(client)
        post(client, wid, bots[0])
        state = settled(
            client, wid, lambda s: any(d["state"] == "blocked" for d in s["deliveries"])
        )
        assert len(state["deliveries"]) == 2
        assert sandboxes.created == 0
        task = client.get(f"/api/bots/{bots[0]}/collaboration-task").json()
        assert task["wait_mode"] == "computer"
