import importlib.util
import json
from pathlib import Path

from agentbot_control.compute_profiles import ComputeProfile

ROOT = Path(__file__).resolve().parents[3]
TENANT = "11111111-1111-1111-1111-111111111111"
SUB = "22222222-2222-2222-2222-222222222222"
OWNER = "33333333-3333-3333-3333-333333333333"
IMAGE = "example.azurecr.io/agentbot-sandbox@sha256:" + "ab" * 32
ML_ID = (
    f"/subscriptions/{SUB}/resourceGroups/agentcontrol-pilot/providers/"
    "Microsoft.MachineLearningServices/workspaces/agentcontrol-ml/computes/dedicated-pilot"
)
VM_ID = (
    f"/subscriptions/{SUB}/resourceGroups/agentcontrol-pilot/providers/"
    "Microsoft.Compute/virtualMachines/dedicated-linux"
)


def script():
    spec = importlib.util.spec_from_file_location("azure_infra", ROOT / "deploy" / "azure-infra.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_fill_profiles_from_recorded_az_json():
    module = script()
    template = json.loads((ROOT / "deploy" / "azure" / "compute-profiles.example.json").read_text())
    profiles = module.fill_profiles(
        template,
        account={"id": SUB, "tenantId": TENANT, "name": "Pilot"},
        user={"id": OWNER, "userPrincipalName": "ada@example.com"},
        ml_compute={"id": ML_ID, "name": "dedicated-pilot", "location": "eastus"},
        virtual_machine={"id": VM_ID, "name": "dedicated-linux", "location": "eastus"},
        workspace_id="workspace-1",
        owner_username="ada",
        manager="ada",
        administrator="operator",
        image=IMAGE,
    )
    by_id = {item["id"]: item for item in profiles}
    assert by_id["ml-pilot"]["tenant_id"] == TENANT
    assert by_id["ml-pilot"]["subscription_id"] == SUB
    assert by_id["vm-pilot"]["tenant_id"] == TENANT
    assert by_id["vm-pilot"]["subscription_id"] == SUB
    assert by_id["ml-pilot"]["assigned_users"] == {OWNER: "ada"}
    assert by_id["ml-pilot"]["allowed_resources"] == [ML_ID]
    assert by_id["vm-pilot"]["allowed_resources"] == [VM_ID]
    assert by_id["ml-pilot"]["identity"] == "azure_cli"
    assert "create" not in by_id["ml-pilot"]["allowed_operations"]
    assert "delete" not in by_id["vm-pilot"]["allowed_operations"]
    validated = [ComputeProfile.model_validate(item) for item in profiles]
    assert validated[0].tenant_id == TENANT
    assert validated[1].subscription_id == SUB


def test_azure_cli_records_fill_workspace_user_and_image():
    module = script()
    user = {"id": OWNER, "userPrincipalName": "ada@example.com", "mailNickname": None}
    assert module.control_username(user) == "ada"
    groups = [
        {"name": "other", "tags": {"agentcontrol-workspace-id": "workspace_other"}},
        {"name": "agentcontrol-pilot", "tags": {"agentcontrol-workspace-id": "workspace_pilot"}},
    ]
    assert module.workspace_from_groups(groups, "agentcontrol-pilot") == "workspace_pilot"
    manifests = [
        {"digest": "sha256:" + "ab" * 32, "tags": ["latest"], "lastUpdateTime": "2024-01-01T00:00:00Z"},
        {"digest": "sha256:" + "cd" * 32, "tags": ["older"], "lastUpdateTime": "2026-01-01T00:00:00Z"},
    ]
    digest = module.choose_manifest_digest(manifests)
    image = module.pinned_sandbox_image("example.azurecr.io", digest)
    assert image == "example.azurecr.io/agentbot-sandbox@" + digest
    ComputeProfile.model_validate(
        module.fill_profiles(
            json.loads((ROOT / "deploy" / "azure" / "compute-profiles.example.json").read_text()),
            account={"id": SUB, "tenantId": TENANT},
            user=user,
            ml_compute={"id": ML_ID},
            virtual_machine={"id": VM_ID},
            workspace_id="workspace_pilot",
            owner_username=module.control_username(user),
            manager=module.control_username(user),
            administrator=module.control_username(user),
            image=image,
        )[0]
    )


def test_image_version_and_env_assignment_stay_local():
    module = script()
    assert module.pick_image_version(["24.04.202401010", "latest", "24.04.202509220"]) == "24.04.202509220"
    updated = module.set_env_assignment(
        "OPENAI_API_KEY=secret\nCONTROL_COMPUTE_PROFILES=\n",
        "CONTROL_COMPUTE_PROFILES",
        r"C:\work\github\dinhduy\ai-bots\deploy\azure\compute-profiles.json",
    )
    assert "OPENAI_API_KEY=secret" in updated
    assert updated.count("CONTROL_COMPUTE_PROFILES=") == 1
    assert "compute-profiles.json" in updated
