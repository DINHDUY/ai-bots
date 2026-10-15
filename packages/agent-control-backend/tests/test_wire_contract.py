from agentbot_control.wire import WireFrame
from control_support import _app as _app
from fastapi.testclient import TestClient
from pydantic import TypeAdapter
from runtime_support import decide as decide
from runtime_support import setup as setup
from runtime_support import start as start
from runtime_support import wait_state as wait_state


def test_exported_contract_accepts_real_replay_and_approval_frames(tmp_path):
    app, _, _, _ = _app(tmp_path)
    validator = TypeAdapter(WireFrame)
    with TestClient(app) as client:
        bot = setup(client)
        assert start(client, bot).status_code == 202
        state = wait_state(client, bot, lambda value: bool(value["pending_approvals"]))
        with client.websocket_connect(f"/api/bots/{bot}/events/ws") as observer:
            validator.validate_python(observer.receive_json())
            validator.validate_python(observer.receive_json())
            assert decide(client, bot, state["pending_approvals"][0]["id"]).status_code == 200
            while True:
                event = observer.receive_json()
                validator.validate_python(event)
                if event["type"] == "run.finished":
                    break
