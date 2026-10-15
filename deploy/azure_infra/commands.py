from __future__ import annotations

import json
import shlex
import shutil
import subprocess

from deploy.azure_infra.constants import USERNAME


class AzError(RuntimeError):
    pass


class Az:
    def __init__(self, executable):
        self.executable = executable

    def run(self, args, *, check=True, capture=True):
        completed = subprocess.run(
            [self.executable, *args],
            check=False,
            capture_output=capture,
            text=True,
        )
        if check and completed.returncode != 0:
            detail = ""
            if capture:
                detail = (completed.stderr or completed.stdout or "").strip()
            raise AzError(detail or f"az exited {completed.returncode}")
        return completed


def az_executable():
    found = shutil.which("az")
    if not found:
        raise SystemExit("Install the Azure CLI and sign in before running this script.")
    return found


def is_missing(completed):
    if completed.returncode == 0:
        return False
    if completed.returncode == 3:
        return True
    text = f"{completed.stderr or ''}\n{completed.stdout or ''}".lower()
    if any(
        token in text for token in ("authorizationfailed", "forbidden", "insufficient privileges")
    ):
        return False
    return "not found" in text or "notfound" in text


def show(az, args):
    completed = az.run([*args, "-o", "json"], check=False)
    if completed.returncode == 0:
        return json.loads(completed.stdout)
    if is_missing(completed):
        return None
    detail = (completed.stderr or completed.stdout or "").strip()
    raise AzError(detail or f"az exited {completed.returncode}")


def with_arm_id(document, fallback):
    resource_id = str((document or {}).get("id") or "")
    if resource_id.startswith("/subscriptions/"):
        return {**(document or {}), "id": resource_id}
    return {**(document or {}), "id": fallback}


def subscription_of(resource_id):
    parts = resource_id.strip("/").split("/")
    if len(parts) < 2 or parts[0].lower() != "subscriptions":
        raise SystemExit(f"Azure resource id is missing a subscription: {resource_id}")
    return parts[1]


def ml_resource_id(subscription, group, workspace, name):
    return (
        f"/subscriptions/{subscription}/resourceGroups/{group}"
        f"/providers/Microsoft.MachineLearningServices/workspaces/{workspace}/computes/{name}"
    )


def vm_resource_id(subscription, group, name):
    return (
        f"/subscriptions/{subscription}/resourceGroups/{group}"
        f"/providers/Microsoft.Compute/virtualMachines/{name}"
    )


def subnet_resource_id(subscription, group, vnet, subnet):
    return (
        f"/subscriptions/{subscription}/resourceGroups/{group}"
        f"/providers/Microsoft.Network/virtualNetworks/{vnet}/subnets/{subnet}"
    )


def control_username(user):
    principal = str(user.get("userPrincipalName") or "")
    local = principal.split("@", 1)[0]
    for candidate in (user.get("mailNickname"), local):
        value = str(candidate or "").strip()
        if USERNAME.fullmatch(value):
            return value
    return None


def display(args):
    return "az " + shlex.join(args)
