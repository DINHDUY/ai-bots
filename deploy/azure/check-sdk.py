"""Validate real Azure SDK create models without credentials or cloud requests."""

import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "packages/agent-control-backend/src"))
from agentbot_control.compute_profiles import ComputeProfile  # noqa: E402
from agentbot_control.providers.azure import AzureDriver  # noqa: E402


class ML:
    def begin_create_or_update(self, item):
        rest = item._to_rest_object()
        encoded = rest.as_dict()
        assert item.create_on_behalf_of.user_object_id == "owner-object"
        assert item.enable_node_public_ip is False
        assert (
            item.setup_scripts.creation_script.path == "Users/operator/ml-bootstrap.sh"
        )
        assert (
            encoded["properties"]["properties"]["personalComputeInstanceSettings"][
                "assignedUser"
            ]["objectId"]
            == "owner-object"
        )
        return SimpleNamespace()


class VM:
    def begin_create_or_update(self, rg, name, params):
        from azure.mgmt.compute.models import VirtualMachine

        # Current mgmt SDK accepts REST dictionaries or public model objects.
        assert isinstance(params, VirtualMachine)
        value = params
        assert value.storage_profile.data_disks[0].lun == 0
        assert not getattr(
            value.network_profile.network_interfaces[0], "public_ip_address", None
        )
        return SimpleNamespace()


async def main():
    values = json.loads(
        (ROOT / "deploy/azure/compute-profiles.example.json").read_text()
    )
    for raw in values:
        raw.update(
            allowed_operations=["create", "stop"],
            bootstrap_url="https://example.test/bootstrap.sh",
            bootstrap_sha256="a" * 64,
            package_url="https://example.test/package.zip",
            package_sha256="b" * 64,
            key_vault_url="https://vault.vault.azure.net",
            backend_url="https://control.example.test",
            host_identity_resource_id="/subscriptions/22222222-2222-2222-2222-222222222222/resourceGroups/agentcontrol-pilot/providers/Microsoft.ManagedIdentity/userAssignedIdentities/host",
            host_identity_client_id="33333333-3333-3333-3333-333333333333",
            subnet_id="/subscriptions/22222222-2222-2222-2222-222222222222/resourceGroups/agentcontrol-pilot/providers/Microsoft.Network/virtualNetworks/pilot/subnets/hosts",
            ssh_public_key="ssh-ed25519 AAAATEST",
            ml_bootstrap_path="Users/operator/ml-bootstrap.sh",
        )
        raw["vm_image"] = {
            "publisher": "Canonical",
            "offer": "ubuntu-24_04-lts",
            "sku": "server",
            "version": "24.04.202601010",
        }  # Serialization fixture only; no image availability claim.
        p = ComputeProfile.model_validate(raw)
        nic = SimpleNamespace(
            begin_create_or_update=lambda *args: SimpleNamespace(
                result=lambda **kwargs: SimpleNamespace(id="/approved/nic")
            )
        )
        driver = AzureDriver(
            p,
            ml=SimpleNamespace(compute=ML()),
            compute=SimpleNamespace(virtual_machines=VM()),
            network=SimpleNamespace(network_interfaces=nic),
        )
        await driver.submit(
            "create",
            p.allowed_resources[0],
            "sdk-probe",
            tags={},
            bootstrap="#!/bin/bash\ntrue\n",
            owner_object_id="owner-object",
        )
        print(p.provider + ": SDK model serialization passed; no Azure requests")


if __name__ == "__main__":
    asyncio.run(main())
