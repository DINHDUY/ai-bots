import json
import time

import pytest
from control_support import _app as _app
from control_support import _create_bot as _create_bot
from control_support import _register as _register
from fastapi.testclient import TestClient
from runtime_support import decide as decide
from runtime_support import start as start
from runtime_support import wait_state as wait_state
from starlette.websockets import WebSocketDisconnect
from workspace_services_support import LiveManager as LiveManager
from workspace_services_support import LiveSandbox as LiveSandbox
from workspace_services_support import create_computer as create_computer
from workspace_services_support import live_app as live_app
from workspace_services_support import png as png


def test_inspection_never_creates_and_capture_is_scoped(tmp_path):
    app, manager = live_app(tmp_path)
    with TestClient(app) as owner, TestClient(app) as foreign:
        _register(owner)
        bid = _create_bot(owner).json()["id"]
        assert owner.get(f"/api/bots/{bid}/computer").json()["computer"] is None
        assert manager.created == 0
        computer = create_computer(owner, bid)
        sandbox = manager._cache[computer["id"]]
        sandbox.degraded = True
        report = owner.get(f"/api/bots/{bid}/computer").json()
        assert report["health"] == "degraded" and report["services"]["desktop"]
        assert app.state.runtime.store.computer(bid)["updated_at"] == computer["updated_at"]
        capture = owner.post(
            f"/api/bots/{bid}/computer/capture", json={"request_id": "capture_now_1"}
        ).json()
        assert capture["capture"]["width"] == 2
        assert "secret" not in json.dumps(capture)
        assert owner.get(capture["url"]).content == png()
        _register(foreign, "foreign")
        assert foreign.get(capture["url"]).status_code == 404
        owner.post(
            f"/api/bots/{bid}/lifecycle/hibernate",
            json={"request_id": "hibernate_1", "generation": 1},
        )
        assert owner.get(f"/api/bots/{bid}/computer").json()["lifecycle"] == "exited"
        assert manager.created == 1 and sandbox.stopped


def test_control_fences_tabs_input_disconnect_and_private_recording(tmp_path):
    app, manager = live_app(tmp_path)
    with TestClient(app) as client:
        _register(client)
        bid = _create_bot(client).json()["id"]
        computer = create_computer(client, bid)
        sid = computer["id"]
        base = f"/api/bots/{bid}/sessions/{sid}/control"
        acquire = {
            "request_id": "take_control_1",
            "client_id": "first_tab",
            "generation": 1,
            "surface": "browser",
        }
        lease = client.post(base + "/acquire", json=acquire).json()
        assert "fence" in lease, lease
        assert client.post(base + "/acquire", json=acquire).json()["id"] == lease["id"]
        assert (
            client.post(base + "/acquire", json={**acquire, "client_id": "other_tab"}).status_code
            == 409
        )
        assert start(client, bid).status_code == 409
        command = {
            "request_id": "lease_command_1",
            "client_id": "first_tab",
            "lease_id": lease["id"],
            "fence": lease["fence"],
        }
        recordbase = f"/api/bots/{bid}/sessions/{sid}/recordings"
        assert client.post(recordbase, json={**command, "operation": "start"}).status_code == 200
        query = f"lease_id={lease['id']}&client_id=first_tab&fence={lease['fence']}"
        with client.websocket_connect(base + "/ws?" + query) as socket:
            cap = client.get(f"/api/bots/{bid}/captures/latest").json()
            packet = {
                **command,
                "generation": 1,
                "surface_id": lease["surface_id"],
                "viewport_revision": lease["viewport_revision"],
                "capture_id": cap["capture_id"],
                "sequence": 1,
                "input": {"kind": "down", "x": 0, "y": 1},
            }
            socket.send_json({**packet, "generation": 2})
            assert socket.receive_json()["status"] == "rejected"
            socket.send_json({**packet, "viewport_revision": "old_viewport"})
            assert socket.receive_json()["status"] == "rejected"
            socket.send_json({**packet, "input": {"kind": "down", "x": 200, "y": 1}})
            assert socket.receive_json()["status"] == "rejected"
            socket.send_json(packet)
            assert socket.receive_json()["status"] == "applied"
            socket.send_json(packet)
            assert socket.receive_json()["status"] == "duplicate"
            assert (
                client.post(recordbase, json={**command, "operation": "private"}).status_code == 200
            )
            cap = client.get(f"/api/bots/{bid}/captures/latest").json()
            time.sleep(0.02)
            socket.send_json(
                {
                    **packet,
                    "capture_id": cap["capture_id"],
                    "sequence": 2,
                    "input": {"kind": "key_down", "key": "s"},
                }
            )
            assert socket.receive_json()["status"] == "applied"
            assert (
                client.get(f"/api/bots/{bid}/captures/latest").json()["capture_id"]
                == cap["capture_id"]
            )
        state = client.get(base).json()
        assert state["paused"] and state["lease"] is None
        assert client.post(base + "/acquire", json=acquire).status_code == 409
        assert manager._cache[sid].inputs[-1][1]["kind"] == "release"
        recordings = client.get(f"/api/bots/{bid}/toolkit").json()["recordings"]
        assert len(json.loads(recordings[0]["steps"])) == 1
        assert start(client, bid, "after_release_1").status_code == 409
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect(base + "/ws?" + query) as socket:
                socket.receive_json()


def test_lifecycle_preserves_file_then_resets_once(tmp_path):
    app, manager = live_app(tmp_path)
    with TestClient(app) as client:
        _register(client)
        bid = _create_bot(client).json()["id"]
        computer = create_computer(client, bid)
        sid = computer["id"]
        manager._cache[sid].files["/workspace/saved"] = "data"
        for operation in ("hibernate", "resume"):
            result = client.post(
                f"/api/bots/{bid}/lifecycle/{operation}",
                json={"request_id": operation + "_request", "generation": 1},
            ).json()
            assert result["status"] == "completed", result
        assert manager._cache[sid].files["/workspace/saved"] == "data"
        assert manager._cache[sid].epoch == 2
        reset = {"request_id": "reset_request_1", "generation": 1}
        result = client.post(f"/api/bots/{bid}/lifecycle/reset", json=reset).json()
        assert result["computer"]["generation"] == 2
        assert manager._cache[result["computer"]["id"]].files == {}
        assert client.post(f"/api/bots/{bid}/lifecycle/reset", json=reset).json() == result
        assert manager.created == 2
        assert (
            client.post(
                f"/api/bots/{bid}/lifecycle/close",
                json={"request_id": "stale_close_1", "generation": 1},
            ).status_code
            == 409
        )


def test_workspace_roles_grants_revocation_and_search(tmp_path):
    app, _, _, _ = _app(tmp_path)
    with TestClient(app) as owner, TestClient(app) as operator:
        _register(owner)
        _register(operator, "operator")
        wid = owner.post("/api/workspaces", json={"name": "Team"}).json()["id"]
        bid = _create_bot(owner, workspace_id=wid, name="TeamMarker").json()["id"]
        private = _create_bot(owner, name="PrivateMarker").json()["id"]
        assert len(owner.get("/api/workspaces").json()) == 2
        assert operator.get(f"/api/bots/{bid}").status_code == 404
        owner.post(
            f"/api/workspaces/{wid}/members",
            json={"username": "operator", "role": "viewer"},
        )
        assert operator.get(f"/api/bots/{bid}").status_code == 200
        assert start(operator, bid).status_code == 403
        assert operator.get(f"/api/bots/{bid}/approval-policies").status_code == 403
        assert operator.get(f"/api/bots/{private}").status_code == 404
        result = operator.get(f"/api/workspaces/{wid}/search?q=Marker").json()
        assert all(h["bot_id"] != private for h in result["hits"])
        owner.post(
            f"/api/workspaces/{wid}/members",
            json={"username": "operator", "role": "operator"},
        )
        assert start(operator, bid).status_code == 403
        owner.post(
            f"/api/bots/{bid}/execution-grants",
            json={"username": "operator", "enabled": True},
        )
        assert start(operator, bid).status_code == 202
        state = wait_state(operator, bid, lambda s: bool(s["pending_approvals"]))
        aid = state["pending_approvals"][0]["id"]
        with operator.websocket_connect(
            f"/api/bots/{bid}/events/ws?after_seq={state['snapshot_seq']}"
        ) as socket:
            assert socket.receive_json()["type"] == "ready"
            owner.post(
                f"/api/workspaces/{wid}/members",
                json={"username": "operator", "role": "remove"},
            )
            with pytest.raises(WebSocketDisconnect):
                for _ in range(20):
                    socket.receive_json()
        assert decide(operator, bid, aid).status_code == 404
        assert operator.get(f"/api/workspaces/{wid}/search?q=TeamMarker").status_code == 404


def test_selected_share_and_preferences_conflict(tmp_path):
    app, _ = live_app(tmp_path)
    with TestClient(app) as owner, TestClient(app) as viewer:
        _register(owner)
        _register(viewer, "viewer")
        bid = _create_bot(owner).json()["id"]
        computer = create_computer(owner, bid)
        owner.post(f"/api/bots/{bid}/computer/capture", json={"request_id": "capture_share"})
        grant = owner.post(
            f"/api/bots/{bid}/shares",
            json={
                "username": "viewer",
                "session_id": computer["id"],
                "surfaces": ["browser"],
            },
        ).json()
        shared = viewer.get(f"/api/shares/{grant['id']}").json()
        assert len(shared["captures"]) == 1
        assert viewer.get(shared["captures"][0]["url"]).content == png()
        assert viewer.get(f"/api/bots/{bid}/snapshot").status_code == 404
        owner.delete(f"/api/bots/{bid}/shares/{grant['id']}")
        assert viewer.get(shared["captures"][0]["url"]).status_code == 404
        pref = owner.get("/api/preferences").json()
        assert (
            owner.post("/api/preferences", json={**pref, "display_role": "Owner"}).json()[
                "revision"
            ]
            == 1
        )
        assert owner.post("/api/preferences", json=pref).status_code == 409
