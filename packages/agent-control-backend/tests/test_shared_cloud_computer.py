"""A workspace can attach one Azure computer instead of one computer per bot."""

from cloud_support import RID, step
from cloud_support import cloud as cloud


def test_shared_cloud_attach_and_locked_bot_config(cloud):
    client, service, bot, docker, fake = cloud
    wid = client.get(f"/api/bots/{bot}/snapshot").json()["workspace_id"]
    saved = client.put(
        f"/api/workspaces/{wid}/computer",
        json={
            "request_id": "sharecloud01",
            "expected_revision": 0,
            "mode": "shared",
            "provider": "azure_ml_compute_instance",
            "profile_id": "ml",
            "ownership": "attached",
        },
    )
    assert saved.status_code == 200, saved.text
    denied = client.post(
        f"/api/bots/{bot}/compute-config",
        json={
            "request_id": "select-cloud",
            "provider": "azure_ml_compute_instance",
            "profile_id": "ml",
            "expected_revision": 0,
        },
    )
    assert denied.status_code == 409 and denied.json()["code"] == "workspace_computer"
    accepted = client.post(
        f"/api/workspaces/{wid}/computer/lifecycle",
        json={
            "request_id": "attachshared",
            "operation": "attach",
            "resource_id": RID,
            "expected_revision": saved.json()["revision"],
            "generation": 0,
        },
    )
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["status"] == "accepted"
    step(client, service, accepted.json()["operation_id"])
    computer = service.store.computer(bot)
    assert computer["status"] == "hibernated"
    assert computer["workspace_id"] == wid and computer["bot_id"] is None
    binding = service.binding(workspace_id=wid)
    assert binding["bot_id"] is None and binding["ownership"] == "attached"
    assert docker.created == 0 and fake.calls == []
    assert "session.hibernated" in [
        event["type"] for event in client.get(f"/api/bots/{bot}/snapshot").json()["events"]
    ]
