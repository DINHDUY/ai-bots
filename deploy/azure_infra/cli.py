"""Provision the Azure attach pilot and write compute-profiles.json.

Reads the example profile, fills tenant, subscription, owner, and resource IDs
from Azure CLI, and on --apply creates only the missing resource group, ML
workspace, private subnet, ML compute instance, and Linux VM. Dry-run is the
default. The control backend still does not create those resources itself.
"""

from __future__ import annotations

import argparse
import json
import shlex
import sys
from pathlib import Path

from deploy.azure_infra.commands import (
    Az,
    az_executable,
    control_username,
    display,
    ml_resource_id,
    show,
    vm_resource_id,
    with_arm_id,
)
from deploy.azure_infra.constants import (
    DEFAULT_OUTPUT,
    ENV_KEY,
    EXAMPLE,
    SANDBOX_REPOSITORY,
    WORKSPACE_TAG,
)
from deploy.azure_infra.discovery import (
    discover_sandbox_image,
    discover_workspace_id,
    require_explicit_version,
    tagged_workspace,
    workspace_tag_command,
)
from deploy.azure_infra.profiles import (
    fill_profiles,
    ml_compute_yaml,
    validate_profiles,
    write_env,
    write_profiles,
)
from deploy.azure_infra.provisioning import (
    ensure_group,
    ensure_ml_compute,
    ensure_ml_extension,
    ensure_network,
    ensure_vm,
    ensure_workspace,
)


def manual_steps(output):
    return "\n".join(
        [
            "Remaining operator steps (this script does not run them):",
            "  make install && make azure-install, then restart the control backend.",
            f"  Set {ENV_KEY}={output} if you did not pass --write-env.",
            "  On Ubuntu 24.04, run python3 deploy/azure/build-host-bundle.py.",
            "  Publish that zip and deploy/azure/bootstrap.sh at immutable HTTPS URLs and record the SHA256.",
            "  On each host, mount the persistent disk, write root-only /etc/agentbot/bootstrap.json",
            '  with ownership "attached", and run the checksum-verified bootstrap script.',
            "  Run sudo agentbot-computer-agent identity, then enroll interactively.",
            "  Do not pass the enrollment code as a shell argument.",
            "  Leave managed create disabled until the attach pilot passes.",
            "  Live acceptance (capture, approvals, restart, idle stop) stays a manual check.",
        ]
    )


def parse_args(argv):
    parser = argparse.ArgumentParser(
        description="Fill compute-profiles.json from Azure and create the attach-pilot hosts."
    )
    parser.add_argument(
        "--apply", action="store_true", help="Create missing resources and write the profile."
    )
    parser.add_argument(
        "--write-env",
        action="store_true",
        help="Set CONTROL_COMPUTE_PROFILES in .env. Requires --apply.",
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--subscription", help="Subscription id or name to select before reading the account."
    )
    parser.add_argument("--tenant", help="Expected tenant id. Does not start a new login.")
    parser.add_argument(
        "--workspace-id",
        help=f"Agent Control workspace id. Defaults to the {WORKSPACE_TAG} resource group tag.",
    )
    parser.add_argument(
        "--owner-username",
        help="Agent Control username for the ML owner. Defaults to the signed-in Entra user.",
    )
    parser.add_argument(
        "--owner-object-id", help="Entra object id. Defaults to az ad signed-in-user show."
    )
    parser.add_argument(
        "--manager",
        help="Agent Control manager username. Defaults to the signed-in Entra user.",
    )
    parser.add_argument(
        "--administrator",
        help="Agent Control administrator username. Defaults to the signed-in Entra user.",
    )
    parser.add_argument(
        "--image",
        help=f"Pinned sandbox digest. Defaults to the {SANDBOX_REPOSITORY} repository in an Azure Container Registry.",
    )
    parser.add_argument(
        "--acr",
        help="Container registry name to search. Defaults to every registry in the subscription.",
    )
    parser.add_argument("--region", default="eastus")
    parser.add_argument("--resource-group", default="agentcontrol-pilot")
    parser.add_argument("--ml-workspace", default="agentcontrol-ml")
    parser.add_argument("--ml-name", default="dedicated-pilot")
    parser.add_argument("--vm-name", default="dedicated-linux")
    parser.add_argument("--ml-size", default="Standard_DS3_v2")
    parser.add_argument("--vm-size", default="Standard_D4s_v5")
    parser.add_argument("--vnet-name", default="pilot")
    parser.add_argument("--subnet-name", default="hosts")
    parser.add_argument(
        "--ssh-public-key",
        type=Path,
        help="Existing SSH public key. Generated on --apply when omitted.",
    )
    parser.add_argument(
        "--vm-image-version", help="Explicit Ubuntu 24.04 image version. Never latest."
    )
    parser.add_argument("--data-disk-gb", type=int, default=64)
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(sys.argv[1:] if argv is None else argv)
    if args.write_env and not args.apply:
        raise SystemExit("--write-env writes .env and requires --apply.")
    if args.vm_image_version:
        require_explicit_version(args.vm_image_version)
    az = Az(az_executable())
    if args.subscription:
        az.run(["account", "set", "--subscription", args.subscription], capture=False)
    account = json.loads(az.run(["account", "show", "-o", "json"]).stdout)
    if args.tenant and account.get("tenantId", "").lower() != args.tenant.lower():
        raise SystemExit(
            f"Signed-in tenant is {account.get('tenantId')}, not {args.tenant}. "
            "Run az login --tenant for that tenant, then re-run this script."
        )
    if args.owner_object_id:
        user = {"id": args.owner_object_id}
        if not args.owner_username:
            signed_in = json.loads(az.run(["ad", "signed-in-user", "show", "-o", "json"]).stdout)
            user["userPrincipalName"] = signed_in.get("userPrincipalName")
            user["mailNickname"] = signed_in.get("mailNickname")
    else:
        user = json.loads(az.run(["ad", "signed-in-user", "show", "-o", "json"]).stdout)
    owner = args.owner_username or control_username(user)
    manager = args.manager or owner
    administrator = args.administrator or owner
    workspace_id = args.workspace_id or discover_workspace_id(az, args.resource_group)
    image = args.image or discover_sandbox_image(az, args.acr)
    missing = []
    if not workspace_id:
        missing.append(f"--workspace-id (no {WORKSPACE_TAG} tag on a resource group)")
    if not owner:
        missing.append(
            "--owner-username (signed-in user has no 3-32 character mail nickname or UPN local-part)"
        )
    if not image:
        missing.append(
            f"--image (no reachable {SANDBOX_REPOSITORY} repository in Azure Container Registry)"
        )
    if missing:
        raise SystemExit("Azure CLI could not fill: " + "; ".join(missing))
    print(f"workspace-id: {workspace_id}")
    print(f"owner-username: {owner}")
    print(f"manager: {manager}")
    print(f"administrator: {administrator}")
    print(f"image: {image}")
    planned = []
    ensure_ml_extension(az)
    planned.extend(ensure_group(az, args.apply, args.resource_group, args.region))
    shown_group = show(az, ["group", "show", "--name", args.resource_group])
    current_tag = tagged_workspace((shown_group or {}).get("tags"))
    if current_tag != workspace_id:
        tag_command = workspace_tag_command(account["id"], args.resource_group, workspace_id)
        if args.apply:
            print(display(tag_command))
            az.run(tag_command, capture=False)
        else:
            planned.append(tag_command)
    network_plan, subnet_id = ensure_network(
        az,
        args.apply,
        args.resource_group,
        args.region,
        args.vnet_name,
        args.subnet_name,
        account["id"],
    )
    planned.extend(network_plan)
    planned.extend(
        ensure_workspace(az, args.apply, args.resource_group, args.region, args.ml_workspace)
    )
    yaml_text = ml_compute_yaml(
        name=args.ml_name,
        size=args.ml_size,
        region=args.region,
        tenant_id=account["tenantId"],
        owner_object_id=user["id"],
        subnet_id=subnet_id,
    )
    compute_plan, ml_compute = ensure_ml_compute(
        az,
        args.apply,
        group=args.resource_group,
        workspace=args.ml_workspace,
        name=args.ml_name,
        yaml_text=yaml_text,
        subscription=account["id"],
    )
    planned.extend(compute_plan)
    vm_plan, virtual_machine = ensure_vm(az, args.apply, args, account["id"])
    planned.extend(vm_plan)
    profiles = fill_profiles(
        json.loads(EXAMPLE.read_text(encoding="utf-8")),
        account=account,
        user=user,
        ml_compute=with_arm_id(
            ml_compute,
            ml_resource_id(account["id"], args.resource_group, args.ml_workspace, args.ml_name),
        ),
        virtual_machine=with_arm_id(
            virtual_machine,
            vm_resource_id(account["id"], args.resource_group, args.vm_name),
        ),
        workspace_id=workspace_id,
        owner_username=owner,
        manager=manager,
        administrator=administrator,
        image=image,
        resource_group=args.resource_group,
        ml_workspace=args.ml_workspace,
        region=args.region,
        ml_size=args.ml_size,
        vm_size=args.vm_size,
    )
    validate_profiles(profiles)
    output = args.output.resolve()
    rendered = json.dumps(profiles, indent=2)
    if args.apply:
        write_profiles(output, profiles)
        print(f"Wrote {output}")
        if args.write_env:
            write_env(output)
    else:
        print("Dry run. Pass --apply to create missing resources and write the profile.")
        for command in planned:
            if command[:1] == ["ssh-keygen"]:
                print(shlex.join(command))
            else:
                print(display(command))
        if any(item[:3] == ["ml", "compute", "create"] for item in planned):
            print("ML compute file:")
            print(yaml_text)
        print(rendered)
    print(f"{ENV_KEY}={output}")
    print(manual_steps(output))
    return 0
