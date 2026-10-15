import hashlib
import uuid

import pytest
from agentbot.sandbox.docker import DockerSessionManager
from control_support import _app as _app
from control_support import _create_bot as _create_bot
from control_support import _register as _register
from fastapi.testclient import TestClient
from workspace_services_support import create_computer as create_computer

pytestmark = pytest.mark.docker


def test_binary_api_attachments_control_terminal_and_cleanup(tmp_path):
    docker = pytest.importorskip("docker")
    app, _, _, _ = _app(tmp_path)
    manager = DockerSessionManager(client=docker.from_env())
    manager.configure_scope("control", app.state.runtime.store.deployment)
    app.state.kernel.sandboxes = manager
    with TestClient(app) as client:
        _register(client)
        bid = _create_bot(client).json()["id"]
        computer = create_computer(client, bid)
        sid = computer["id"]
        base = f"/api/bots/{bid}/sessions/{sid}"
        try:
            data = bytes(range(256)) * 500
            fields = {
                "request_id": "binary_upload_1",
                "path": "/workspace/binary.bin",
                "expected_revision": "missing",
            }
            upload = client.post(
                base + "/uploads",
                data=fields,
                files={"file": ("binary.bin", data, "application/octet-stream")},
            )
            assert upload.status_code == 201, upload.text
            record = upload.json()
            assert record["revision"] == hashlib.sha256(data).hexdigest()
            again = client.post(
                base + "/uploads",
                data=fields,
                files={"file": ("binary.bin", data, "application/octet-stream")},
            )
            assert again.json()["id"] == record["id"]
            preview = client.get(
                base + "/file-preview", params={"path": "/workspace/binary.bin"}
            ).json()
            assert preview["truncated"] and preview["returned_bytes"] == 65536
            download = client.get(
                base + "/file-content",
                params={
                    "path": "/workspace/binary.bin",
                    "revision": record["revision"],
                },
            )
            assert download.content == data
            assert download.headers["x-content-type-options"] == "nosniff"
            assert download.headers["content-disposition"].startswith("attachment")
            assert (
                client.get(f"/api/bots/{bid}/artifacts/{record['artifact_id']}/content").content
                == data
            )
            overwrite = client.post(
                base + "/uploads",
                data={**fields, "request_id": "overwrite_1"},
                files={"file": ("binary.bin", b"wrong")},
            )
            assert overwrite.status_code == 409
            protected = client.post(
                base + "/uploads",
                data={
                    **fields,
                    "path": "/workspace/.env",
                    "request_id": "secret_upload_1",
                },
                files={"file": (".env", b"TOKEN=x")},
            )
            assert protected.status_code == 403
            lease = client.post(
                base + "/control/acquire",
                json={
                    "request_id": "human_takeover_1",
                    "client_id": "browser_tab_1",
                    "generation": 1,
                },
            ).json()
            assert "fence" in lease, lease
            cmd = {
                "request_id": "terminal_open_1",
                "lease_id": lease["id"],
                "client_id": lease["client_id"],
                "fence": lease["fence"],
            }
            query = f"lease_id={lease['id']}&client_id={lease['client_id']}&fence={lease['fence']}"
            with client.websocket_connect(base + "/control/ws?" + query):
                terminal = client.post(base + "/terminals", json=cmd)
                assert terminal.status_code == 200, terminal.text
                tid = terminal.json()["id"]
                assert any(
                    item["id"] == tid and item["status"] == "open"
                    for item in client.get(base + "/terminals").json()
                )
                with client.websocket_connect(base + f"/terminals/{tid}/ws?" + query) as socket:
                    import base64

                    socket.send_json(
                        {
                            "op": "write",
                            "data": base64.b64encode(b"printf api_pty_ok\\n\n").decode(),
                        }
                    )
                    for _ in range(30):
                        result = socket.receive_json()
                        if result.get("type") == "output" and b"api_pty_ok" in base64.b64decode(
                            result["data"]
                        ):
                            break
                    else:
                        pytest.fail("PTY input/output did not complete")
                assert (
                    client.post(base + f"/terminals/{tid}/close", json=cmd).json()["status"]
                    == "closed"
                )
                assert client.get(base + "/terminals").json()[0]["status"] == "closed"
            state = client.get(base + "/control").json()
            assert state["paused"] and state["lease"] is None
        finally:
            client.post(
                f"/api/bots/{bid}/computer/close",
                json={"request_id": "cleanup_" + uuid.uuid4().hex, "session_id": sid},
            )
