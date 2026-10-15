from __future__ import annotations

import json
import sys

from deploy.azure_infra.commands import subscription_of
from deploy.azure_infra.constants import ATTACH, ENV_KEY, ROOT, SANDBOX_REPOSITORY


def normalize_digest(digest):
    value = str(digest or "").strip().lower()
    hexpart = value[7:] if value.startswith("sha256:") else value
    if len(hexpart) == 64 and all(char in "0123456789abcdef" for char in hexpart):
        return "sha256:" + hexpart
    return None


def choose_manifest_digest(manifests):
    usable = []
    for item in manifests or []:
        digest = normalize_digest(item.get("digest"))
        if not digest:
            continue
        tags = [str(tag) for tag in item.get("tags") or []]
        usable.append((digest, tags, str(item.get("lastUpdateTime") or "")))
    for digest, tags, _stamp in usable:
        if "latest" in tags:
            return digest
    if not usable:
        return None
    return max(usable, key=lambda item: item[2])[0]


def pinned_sandbox_image(login_server, digest, repository=SANDBOX_REPOSITORY):
    pinned = normalize_digest(digest)
    if not pinned or not login_server:
        return None
    return f"{login_server}/{repository}@{pinned}"


def version_key(value):
    parts = []
    for part in value.split("."):
        parts.append(int(part) if part.isdigit() else part)
    return parts


def pick_image_version(versions):
    usable = [item for item in versions if item and str(item).lower() != "latest"]
    if not usable:
        raise SystemExit(
            "No explicit Ubuntu 24.04 image version was returned. Pass --vm-image-version."
        )
    return max(usable, key=version_key)


def fill_profiles(
    template,
    *,
    account,
    user,
    ml_compute,
    virtual_machine,
    workspace_id,
    owner_username,
    manager,
    administrator,
    image,
    resource_group="agentcontrol-pilot",
    ml_workspace="agentcontrol-ml",
    region="eastus",
    ml_size=None,
    vm_size=None,
):
    tenant_id = account["tenantId"]
    subscription_id = account["id"]
    owner_object_id = user["id"]
    ml_id = ml_compute["id"]
    vm_id = virtual_machine["id"]
    for resource_id in (ml_id, vm_id):
        found = subscription_of(resource_id)
        if found.lower() != subscription_id.lower():
            raise SystemExit(
                f"Resource {resource_id} is in subscription {found}, not {subscription_id}."
            )
    profiles = json.loads(json.dumps(template))
    by_id = {item["id"]: item for item in profiles}
    if set(by_id) != {"ml-pilot", "vm-pilot"}:
        raise SystemExit("The example profile must contain ml-pilot and vm-pilot.")
    for profile in profiles:
        profile["tenant_id"] = tenant_id
        profile["subscription_id"] = subscription_id
        profile["workspace_id"] = workspace_id
        profile["resource_group"] = resource_group
        profile["region"] = region
        profile["image"] = image
        profile["identity"] = "azure_cli"
        profile["managers"] = [manager]
        profile["administrators"] = [administrator]
        profile["allowed_operations"] = list(ATTACH)
    ml = by_id["ml-pilot"]
    ml["ml_workspace"] = ml_workspace
    ml["assigned_users"] = {owner_object_id: owner_username}
    ml["allowed_resources"] = [ml_id]
    if ml_size:
        ml["sizes"] = [ml_size]
        ml["default_size"] = ml_size
    vm = by_id["vm-pilot"]
    vm["allowed_resources"] = [vm_id]
    if vm_size:
        vm["sizes"] = [vm_size]
        vm["default_size"] = vm_size
    return profiles


def ml_compute_yaml(*, name, size, region, tenant_id, owner_object_id, subnet_id):
    return "\n".join(
        [
            "$schema: https://azuremlschemas.azureedge.net/latest/computeInstance.schema.json",
            f"name: {name}",
            "type: computeinstance",
            f"size: {size}",
            f"location: {region}",
            "enable_node_public_ip: false",
            "ssh_public_access_enabled: false",
            "enable_root_access: true",
            "create_on_behalf_of:",
            f"  user_tenant_id: {tenant_id}",
            f"  user_object_id: {owner_object_id}",
            "network_settings:",
            f"  subnet: {subnet_id}",
            "",
        ]
    )


def format_env_value(value):
    if any(char in value for char in " \t#"):
        return '"' + value.replace('"', '\\"') + '"'
    return value


def set_env_assignment(text, key, value):
    line = f"{key}={format_env_value(value)}"
    rows = text.splitlines()
    prefix = f"{key}="
    found = False
    updated = []
    for row in rows:
        if row.startswith(prefix) or row.startswith(f"{key} ="):
            updated.append(line)
            found = True
        else:
            updated.append(row)
    if not found:
        if updated and updated[-1] == "":
            updated[-1] = line
        else:
            updated.append(line)
    body = "\n".join(updated)
    if text.endswith("\n") or text == "":
        body += "\n"
    return body


def validate_profiles(profiles):
    try:
        from agentbot_control.compute_profiles import ComputeProfile
    except ImportError:
        backend = ROOT / "packages" / "agent-control-backend" / "src"
        sys.path.insert(0, str(backend))
        try:
            from agentbot_control.compute_profiles import ComputeProfile
        except ImportError as exc:
            raise SystemExit(
                "Install the control backend (make install) so the profile can be validated."
            ) from exc
    try:
        return [ComputeProfile.model_validate(item) for item in profiles]
    except Exception as exc:
        raise SystemExit(f"Compute profile is invalid: {exc}") from exc


def write_profiles(path, profiles):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(profiles, indent=2) + "\n", encoding="utf-8")
    loaded = json.loads(path.read_text(encoding="utf-8"))
    validate_profiles(loaded)


def write_env(path):
    env_path = ROOT / ".env"
    current = env_path.read_text(encoding="utf-8") if env_path.exists() else ""
    env_path.write_text(set_env_assignment(current, ENV_KEY, str(path)), encoding="utf-8")
    print(f"Updated {env_path} {ENV_KEY}")
