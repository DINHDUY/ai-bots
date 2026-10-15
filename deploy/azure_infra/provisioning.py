from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path

from deploy.azure_infra.commands import (
    AzError,
    display,
    ml_resource_id,
    show,
    subnet_resource_id,
    vm_resource_id,
)
from deploy.azure_infra.constants import (
    ADMIN_USERNAME,
    IMAGE_OFFER,
    IMAGE_PUBLISHER,
    IMAGE_SKU,
    ROOT,
    SUBNET_PREFIX,
    VNET_PREFIX,
)
from deploy.azure_infra.discovery import resolve_image_version


def ensure_ml_extension(az):
    listed = az.run(["extension", "list", "-o", "json"])
    names = {item.get("name") for item in json.loads(listed.stdout)}
    if "ml" in names:
        return
    command = ["extension", "add", "--name", "ml"]
    print(display(command))
    az.run(command, capture=False)


def ensure_group(az, apply, name, region):
    if show(az, ["group", "show", "--name", name]):
        return []
    command = ["group", "create", "--name", name, "--location", region]
    if not apply:
        return [command]
    print(display(command))
    az.run(command, capture=False)
    return []


def ensure_network(az, apply, group, region, vnet, subnet, subscription):
    planned = []
    existing = show(az, ["network", "vnet", "show", "--resource-group", group, "--name", vnet])
    if existing is None:
        command = [
            "network",
            "vnet",
            "create",
            "--resource-group",
            group,
            "--name",
            vnet,
            "--location",
            region,
            "--address-prefixes",
            VNET_PREFIX,
            "--subnet-name",
            subnet,
            "--subnet-prefixes",
            SUBNET_PREFIX,
        ]
        if not apply:
            planned.append(command)
            return planned, subnet_resource_id(subscription, group, vnet, subnet)
        print(display(command))
        az.run(command, capture=False)
    subnet_doc = show(
        az,
        [
            "network",
            "vnet",
            "subnet",
            "show",
            "--resource-group",
            group,
            "--vnet-name",
            vnet,
            "--name",
            subnet,
        ],
    )
    if subnet_doc is None:
        command = [
            "network",
            "vnet",
            "subnet",
            "create",
            "--resource-group",
            group,
            "--vnet-name",
            vnet,
            "--name",
            subnet,
            "--address-prefixes",
            SUBNET_PREFIX,
        ]
        if not apply:
            planned.append(command)
            return planned, subnet_resource_id(subscription, group, vnet, subnet)
        print(display(command))
        az.run(command, capture=False)
        subnet_doc = show(
            az,
            [
                "network",
                "vnet",
                "subnet",
                "show",
                "--resource-group",
                group,
                "--vnet-name",
                vnet,
                "--name",
                subnet,
            ],
        )
    if subnet_doc is None:
        raise AzError(f"Subnet {subnet} was not found after create.")
    return planned, subnet_doc["id"]


def ensure_workspace(az, apply, group, region, name):
    if show(az, ["ml", "workspace", "show", "--resource-group", group, "--name", name]):
        return []
    command = [
        "ml",
        "workspace",
        "create",
        "--resource-group",
        group,
        "--name",
        name,
        "--location",
        region,
    ]
    if not apply:
        return [command]
    print(display(command))
    az.run(command, capture=False)
    return []


def ensure_ml_compute(az, apply, *, group, workspace, name, yaml_text, subscription):
    existing = show(
        az,
        [
            "ml",
            "compute",
            "show",
            "--resource-group",
            group,
            "--workspace-name",
            workspace,
            "--name",
            name,
        ],
    )
    if existing:
        return [], existing
    command = [
        "ml",
        "compute",
        "create",
        "--resource-group",
        group,
        "--workspace-name",
        workspace,
        "--file",
        "<ml-compute.yml>",
    ]
    document = {"id": ml_resource_id(subscription, group, workspace, name), "name": name}
    if not apply:
        return [command], document
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".yml", prefix="agentcontrol-ml-", delete=False, encoding="utf-8"
    ) as handle:
        handle.write(yaml_text)
        path = handle.name
    try:
        command[-1] = path
        print(display(command))
        az.run(command, capture=False)
    finally:
        Path(path).unlink(missing_ok=True)
    created = show(
        az,
        [
            "ml",
            "compute",
            "show",
            "--resource-group",
            group,
            "--workspace-name",
            workspace,
            "--name",
            name,
        ],
    )
    if created is None:
        raise AzError(f"ML compute {name} was not found after create.")
    return [], created


def public_key_path(args):
    if args.ssh_public_key:
        return args.ssh_public_key
    return ROOT / "deploy" / "azure" / "keys" / f"{args.vm_name}_ed25519.pub"


def ensure_ssh_key(path, apply):
    if path.exists():
        return []
    if not apply:
        return [
            [
                "ssh-keygen",
                "-t",
                "ed25519",
                "-f",
                str(path.with_suffix("")),
                "-N",
                "",
                "-C",
                ADMIN_USERNAME,
            ]
        ]
    private = path.with_suffix("") if path.suffix == ".pub" else path
    keygen = shutil.which("ssh-keygen")
    if not keygen:
        raise SystemExit(f"Pass --ssh-public-key or install ssh-keygen. Missing {path}.")
    private.parent.mkdir(parents=True, exist_ok=True)
    print(f"ssh-keygen -t ed25519 -f {private} -N '' -C {ADMIN_USERNAME}")
    completed = subprocess.run(
        [keygen, "-t", "ed25519", "-f", str(private), "-N", "", "-q", "-C", ADMIN_USERNAME],
        check=False,
        text=True,
    )
    if completed.returncode != 0 or not path.exists():
        raise SystemExit(f"ssh-keygen did not write {path}.")
    return []


def nic_resource_id(subscription, group, name):
    return (
        f"/subscriptions/{subscription}/resourceGroups/{group}"
        f"/providers/Microsoft.Network/networkInterfaces/{name}"
    )


def ensure_vm(az, apply, args, subscription):
    existing = show(
        az,
        ["vm", "show", "--resource-group", args.resource_group, "--name", args.vm_name],
    )
    if existing:
        return [], existing
    image_version = resolve_image_version(az, args.vm_image_version)
    nic_name = args.vm_name + "-nic"
    nic = show(
        az, ["network", "nic", "show", "--resource-group", args.resource_group, "--name", nic_name]
    )
    planned = []
    if nic is None:
        nic_command = [
            "network",
            "nic",
            "create",
            "--resource-group",
            args.resource_group,
            "--name",
            nic_name,
            "--vnet-name",
            args.vnet_name,
            "--subnet",
            args.subnet_name,
            "--location",
            args.region,
        ]
        if not apply:
            planned.append(nic_command)
            nic = {"id": nic_resource_id(subscription, args.resource_group, nic_name)}
        else:
            print(display(nic_command))
            az.run(nic_command, capture=False)
            nic = show(
                az,
                [
                    "network",
                    "nic",
                    "show",
                    "--resource-group",
                    args.resource_group,
                    "--name",
                    nic_name,
                ],
            )
    if nic is None or not nic.get("id"):
        raise AzError(f"NIC {nic_name} was not found after create.")
    key = public_key_path(args)
    planned.extend(ensure_ssh_key(key, apply))
    # The first empty data disk is LUN 0, which the host bootstrap mounts.
    urn = f"{IMAGE_PUBLISHER}:{IMAGE_OFFER}:{IMAGE_SKU}:{image_version}"
    vm_command = [
        "vm",
        "create",
        "--resource-group",
        args.resource_group,
        "--name",
        args.vm_name,
        "--nics",
        nic["id"],
        "--image",
        urn,
        "--size",
        args.vm_size,
        "--admin-username",
        ADMIN_USERNAME,
        "--ssh-key-values",
        str(key),
        "--data-disk-sizes-gb",
        str(args.data_disk_gb),
        "--location",
        args.region,
    ]
    document = {
        "id": vm_resource_id(subscription, args.resource_group, args.vm_name),
        "name": args.vm_name,
    }
    if not apply:
        planned.append(vm_command)
        return planned, document
    if not key.exists():
        raise SystemExit(f"SSH public key does not exist: {key}")
    print(display(vm_command))
    az.run(vm_command, capture=False)
    created = show(
        az, ["vm", "show", "--resource-group", args.resource_group, "--name", args.vm_name]
    )
    if created is None:
        raise AzError(f"VM {args.vm_name} was not found after create.")
    return [], created
