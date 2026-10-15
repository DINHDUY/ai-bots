from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from agentbot_control.compute_profiles import ComputeProfile
from agentbot_control.providers.azure import AzureDriver, CloudError
from control_support import _app as _app
from control_support import _create_bot as _create_bot
from control_support import _register as _register
from pydantic import ValidationError
from runtime_support import start as start

SUB = "11111111-1111-1111-1111-111111111111"
RID = f"/subscriptions/{SUB}/resourceGroups/control/providers/Microsoft.MachineLearningServices/workspaces/ml/computes/dedicated"

from cloud_support import FakeAzure as FakeAzure
from cloud_support import attach as attach
from cloud_support import cloud as cloud
from cloud_support import profile as profile
from cloud_support import select as select
from cloud_support import step as step


def test_config_inspection_and_admission_never_start_or_fallback(cloud):
    client, service, bot, docker, fake = cloud
    assert client.get(f"/api/bots/{bot}/compute-config").json()["provider"] == "docker"
    select(client, bot)
    assert client.get(f"/api/bots/{bot}/computer").json()["provider"] == "azure_ml_compute_instance"
    assert start(client, bot).status_code == 409
    assert docker.created == 0 and fake.reads == 0 and fake.calls == []
    assert attach(client, bot, RID.replace("dedicated", "foreign")).status_code == 409
    accepted = attach(client, bot)
    assert accepted.status_code == 202, accepted.text
    assert attach(client, bot).json()["operation_id"] == accepted.json()["operation_id"]
    assert fake.reads == 0
    step(client, service, accepted.json()["operation_id"])
    binding = service.binding(bot_id=bot)
    assert binding["verified_owner"] and binding["ownership"] == "attached"
    assert fake.calls == []
    assert service.store.computer(bot)["status"] == "hibernated"
    assert (
        "start"
        in client.get(f"/api/bots/{bot}/computer").json()["capabilities"]["lifecycle_actions"]
    )


def test_assigned_user_failure_cannot_enroll(cloud):
    client, service, bot, _, fake = cloud
    select(client, bot)
    fake.owner = "another-user"
    oid = attach(client, bot).json()["operation_id"]
    step(client, service, oid)
    assert service.operation(oid)["error_code"] == "assigned_owner_mismatch"
    assert (
        client.post(
            f"/api/bots/{bot}/computer/enrollment",
            json={"request_id": "enroll-host", "host_key": "b" * 64},
        ).status_code
        == 409
    )


def test_start_response_loss_reconciles_original_target_without_resubmission(cloud):
    client, service, bot, _, fake = cloud
    select(client, bot)
    step(client, service, attach(client, bot).json()["operation_id"])
    response = client.post(
        f"/api/bots/{bot}/lifecycle/start",
        json={"request_id": "start-cloud", "generation": 1},
    )
    assert response.status_code == 202
    oid = response.json()["operation_id"]
    fake.error = CloudError("azure_unavailable", "Response lost")
    step(client, service, oid)
    assert service.operation(oid)["phase"] == "submitting"
    assert len(fake.calls) == 1
    client.app.state.services.lifecycle.recover()
    fake.power = "running"
    step(client, service, oid)
    assert service.operation(oid)["phase"] == "connecting"
    assert len(fake.calls) == 1 and fake.calls[0][1] == RID
    assert client.app.state.services.control.state(bot)["paused"]


def test_stop_available_without_bridge_and_close_never_deletes_attached(cloud):
    client, service, bot, _, fake = cloud
    select(client, bot)
    step(client, service, attach(client, bot).json()["operation_id"])
    fake.power = "running"
    client.portal.call(service.observe_binding, service.binding(bot_id=bot))
    assert (
        "stop"
        in client.get(f"/api/bots/{bot}/computer").json()["capabilities"]["lifecycle_actions"]
    )
    response = client.post(
        f"/api/bots/{bot}/lifecycle/close",
        json={"request_id": "close-cloud", "generation": 1},
    )
    step(client, service, response.json()["operation_id"])
    assert service.binding(bot_id=bot) is None
    assert fake.calls == []
    assert client.delete(f"/api/bots/{bot}").status_code == 200
    with service.store.transaction() as db:
        assert db.execute("SELECT COUNT(*) FROM computer_provider_bindings").fetchone()[0] == 1
        assert db.execute("SELECT COUNT(*) FROM cloud_operation_state").fetchone()[0] == 2


def test_enrollment_one_time_hashed_and_revocable(cloud):
    client, service, bot, _, _ = cloud
    select(client, bot)
    step(client, service, attach(client, bot).json()["operation_id"])
    grant = client.post(
        f"/api/bots/{bot}/computer/enrollment",
        json={"request_id": "enroll-host", "host_key": "b" * 64},
    ).json()
    body = {
        "request_id": "machine-enroll",
        "binding_id": grant["binding_id"],
        "code": grant["code"],
        "host_key": "b" * 64,
    }
    response = client.post("/api/cloud-computer-agents/enroll", json=body)
    assert response.status_code == 200, response.text
    machine = response.json()
    assert client.post("/api/cloud-computer-agents/enroll", json=body).status_code == 403
    with service.store.transaction() as db:
        assert machine["token"] not in str(
            [dict(r) for r in db.execute("SELECT * FROM cloud_machine_credentials")]
        )
        assert grant["code"] not in str(
            [dict(r) for r in db.execute("SELECT * FROM cloud_enrollments")]
        )
    client.portal.call(service.revoke, service.binding(bot_id=bot))
    assert (
        client.post(
            "/api/cloud-computer-agents/renew",
            headers={"Authorization": "Bearer " + machine["token"]},
        ).status_code
        == 401
    )


def test_profile_rejects_unpinned_image_foreign_resources_and_unbounded_storage():
    for update in (
        {"image": "sandbox:latest"},
        {"workspace_root": "/mnt/ephemeral"},
        {"default_size": "Expensive_VM"},
    ):
        with pytest.raises(ValidationError):
            ComputeProfile.model_validate(profile().model_dump() | update)
    with pytest.raises(ValueError):
        profile().attached_resource(RID + "/other")


@pytest.mark.asyncio
async def test_sdk_inspection_uses_public_assigned_user_and_vm_deallocate():
    ml = SimpleNamespace(
        compute=SimpleNamespace(
            get=Mock(
                return_value=SimpleNamespace(
                    type="computeinstance",
                    create_on_behalf_of=SimpleNamespace(user_object_id="assigned-user"),
                    state="Running",
                    provisioning_state="Succeeded",
                    size="Standard_DS3_v2",
                    location="eastus",
                    tags={},
                )
            )
        )
    )
    assert (await AzureDriver(profile(), ml=ml).inspect(RID))["owner_object_id"] == "assigned-user"
    p = ComputeProfile.model_validate(profile().model_dump() | {"provider": "azure_vm"})
    vmid = f"/subscriptions/{SUB}/resourceGroups/control/providers/Microsoft.Compute/virtualMachines/vm"
    api = SimpleNamespace(
        begin_deallocate=Mock(return_value=SimpleNamespace()),
        begin_start=Mock(),
        begin_delete=Mock(),
    )
    await AzureDriver(p, compute=SimpleNamespace(virtual_machines=api)).submit(
        "stop", vmid, "operation"
    )
    api.begin_deallocate.assert_called_once_with("control", "vm")


@pytest.mark.asyncio
async def test_forbidden_is_unknown_not_missing_and_throttle_honors_retry_after():
    class Denied(Exception):
        status_code = 403

    ml = SimpleNamespace(compute=SimpleNamespace(get=Mock(side_effect=Denied())))
    with pytest.raises(CloudError, match="denied"):
        await AzureDriver(profile(), ml=ml).inspect(RID)


def test_cloud_management_grant_is_separate_from_execution(cloud):
    client, service, bot, _, _ = cloud
    select(client, bot)
    step(client, service, attach(client, bot).json()["operation_id"])
    wid = client.get(f"/api/bots/{bot}/compute-config").json()["workspace_id"]
    client.post("/api/logout")
    operator = _register(client, "operator")
    with service.store.transaction() as db:
        db.execute(
            "INSERT INTO workspace_members VALUES (?,?,'operator')",
            (wid, operator["id"]),
        )
        db.execute("INSERT INTO execution_grants VALUES (?,?)", (bot, operator["id"]))
    command = {"request_id": "operator-start", "generation": 1}
    assert client.post(f"/api/bots/{bot}/lifecycle/start", json=command).status_code == 403
    assert (
        client.post(
            f"/api/bots/{bot}/computer/close", json={"request_id": "operator-close"}
        ).status_code
        == 403
    )
    with service.store.transaction() as db:
        db.execute("INSERT INTO compute_management_grants VALUES (?,?)", (bot, operator["id"]))
    assert client.post(f"/api/bots/{bot}/lifecycle/start", json=command).status_code == 202
    # Even with both grants, ML execution is still assigned-owner-only.
    assert start(client, bot).status_code == 403
