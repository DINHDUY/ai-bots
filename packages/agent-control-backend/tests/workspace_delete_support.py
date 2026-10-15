"""HTTP commands and local deletion recovery fixtures."""

import time


def deletion(client, wid, request_id="delete_workspace_01"):
    response = client.get(f"/api/workspaces/{wid}/deletion-preview")
    assert response.status_code == 200, response.text
    preview = response.json()
    assert not preview["blockers"], preview["blockers"]
    return {
        "request_id": request_id,
        "confirm_name": preview["workspace_name"],
        "preview_digest": preview["preview_digest"],
    }


def deleted(client, wid, request_id="delete_workspace_01"):
    cmd = deletion(client, wid, request_id)
    response = client.post(f"/api/workspaces/{wid}/deletions", json=cmd)
    assert response.status_code in (200, 202), response.text
    return cmd, response.json()


def cleaned(client, request_id="delete_workspace_01", *, state="complete"):
    deadline = time.monotonic() + 6
    while time.monotonic() < deadline:
        response = client.get(f"/api/workspace-deletions/{request_id}")
        assert response.status_code == 200, response.text
        if response.json()["cleanup"]["state"] == state:
            return response.json()
        time.sleep(0.05)
    raise AssertionError(response.text)
