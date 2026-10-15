import threading

import pytest
from agentbot_control.cloud import later
from agentbot_control.compute_profiles import ComputeProfile
from agentbot_control.providers.azure import CloudError
from control_support import _app as _app
from control_support import _create_bot as _create_bot
from control_support import _register as _register
from runtime_support import start as start

SUB = "11111111-1111-1111-1111-111111111111"
RID = f"/subscriptions/{SUB}/resourceGroups/control/providers/Microsoft.MachineLearningServices/workspaces/ml/computes/dedicated"

from cloud_support import FakeAzure as FakeAzure
from cloud_support import attach as attach
from cloud_support import cloud as cloud
from cloud_support import profile as profile
from cloud_support import select as select
from cloud_support import step as step


def test_real_websocket_bridge_fences_lost_mutation_response(cloud):
    from agentbot.interfaces import TerminationUnverified
    from agentbot.sandbox.bridge import HostHello, HostRequest

    client, service, bot, _, _ = cloud
    select(client, bot)
    step(client, service, attach(client, bot).json()["operation_id"])
    grant = client.post(
        f"/api/bots/{bot}/computer/enrollment",
        json={"request_id": "enroll-host", "host_key": "b" * 64},
    ).json()
    machine = client.post(
        "/api/cloud-computer-agents/enroll",
        json={
            "request_id": "machine-enroll",
            "host_key": "b" * 64,
            **{k: grant[k] for k in ("binding_id", "code")},
        },
    ).json()
    headers = {"Authorization": "Bearer " + machine["token"]}
    hello = HostHello(
        binding_id=grant["binding_id"],
        host_key="b" * 64,
        boot_id="test-boot",
        deployment=service.store.deployment,
        image=profile().image,
        session_id=machine["profile"]["session_id"],
        generation=machine["profile"]["generation"],
    )
    with client.websocket_connect("/api/cloud-computer-agents/connect", headers=headers) as control:
        control.send_json(hello.model_dump())
        ack = control.receive_json()
        hello = hello.model_copy(update={"channel": "data", "epoch": ack["epoch"]})
        with client.websocket_connect(
            "/api/cloud-computer-agents/connect", headers=headers
        ) as data:
            data.send_json(hello.model_dump())
            assert data.receive_json()["accepted"]
            observed = []

            def lose_response():
                value = control.receive_json()
                request = HostRequest.model_validate(value)
                request.verify(
                    machine["token"],
                    grant["binding_id"],
                    "test-boot",
                    ack["epoch"],
                    service.store.deployment,
                )
                observed.append(request.method)
                control.close()

            worker = threading.Thread(target=lose_response, daemon=True)
            worker.start()
            with pytest.raises(TerminationUnverified):
                client.portal.call(
                    service.agents.call,
                    service.binding(bot_id=bot),
                    "run_command_checked",
                    {"command": "test"},
                    "test-action",
                )
            worker.join(timeout=3)
            assert observed == ["run_command_checked"]
            assert service.binding(bot_id=bot)["status"] == "quarantined"


def test_managed_create_and_cleanup_survive_response_loss_and_catalog_deletion(cloud):
    client, service, bot, _, fake = cloud
    p = ComputeProfile.model_validate(
        service.profiles["ml"].model_dump()
        | {
            "allowed_operations": ["create", "start", "stop", "close", "delete"],
            "administrators": ["ada"],
            "ml_bootstrap_path": "Users/operator/bootstrap.sh",
            "bootstrap_url": "https://example.test/bootstrap.sh",
            "bootstrap_sha256": "a" * 64,
            "package_url": "https://example.test/package.zip",
            "package_sha256": "b" * 64,
            "key_vault_url": "https://example.vault.azure.net",
            "backend_url": "https://control.example.test",
            "host_identity_resource_id": "/approved/identity",
            "host_identity_client_id": SUB,
        }
    )
    service.profiles["ml"] = p
    response = client.post(
        f"/api/bots/{bot}/compute-config",
        json={
            "request_id": "managed-select",
            "provider": p.provider,
            "profile_id": p.id,
            "ownership": "managed",
            "expected_revision": 0,
        },
    )
    assert response.status_code == 200
    fake.power = "missing"
    command = {"request_id": "managed-create", "generation": 0}
    response = client.post(f"/api/bots/{bot}/lifecycle/create", json=command)
    assert response.status_code == 202, response.text
    oid = response.json()["operation_id"]
    binding = service.binding(bot_id=bot)
    step(client, service, oid)
    assert service.operation(oid)["phase"] == "bootstrap"
    fake.error = CloudError("azure_unavailable", "Lost acceptance")
    step(client, service, oid)
    assert service.operation(oid)["phase"] == "submitting" and len(fake.calls) == 1
    assert (
        client.post(f"/api/bots/{bot}/lifecycle/create", json=command).json()["operation_id"] == oid
    )
    fake.power, fake.error = "running", None
    step(client, service, oid)
    assert service.operation(oid)["phase"] == "connecting" and len(fake.calls) == 1
    # A missing bootstrap hits its deadline without duplicate provisioning.
    service.update(service.operation(oid), deadline=later(-1))
    step(client, service, oid)
    assert service.operation(oid)["phase"] == "outcome_unknown"
    response = client.post(
        f"/api/bots/{bot}/lifecycle/close",
        json={"request_id": "managed-close", "generation": 1},
    )
    step(client, service, response.json()["operation_id"])
    assert client.delete(f"/api/bots/{bot}").status_code == 200
    client.portal.call(service.cleanup, service.binding(binding_id=binding["id"]))
    assert fake.calls[-1][0] == "stop"
    fake.power = "stopped"
    client.portal.call(service.cleanup, service.binding(binding_id=binding["id"]))
    assert service.binding(binding_id=binding["id"])["cleanup_state"] == "retained_stopped"
    assert all(call[0] != "delete" for call in fake.calls)
