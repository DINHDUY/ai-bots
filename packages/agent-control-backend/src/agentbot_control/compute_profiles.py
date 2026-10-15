"""Operator-owned Azure profiles; callers cannot supply cloud credentials or hosts."""

import json
import os
import re
from pathlib import Path, PurePosixPath
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ComputeProfile(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    id: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,64}$")
    name: str = Field(min_length=1, max_length=100)
    workspace_id: str
    provider: Literal["azure_ml_compute_instance", "azure_vm"]
    tenant_id: str = Field(pattern=r"^[0-9a-fA-F-]{36}$")
    subscription_id: str = Field(pattern=r"^[0-9a-fA-F-]{36}$")
    resource_group: str = Field(pattern=r"^[a-zA-Z0-9_.()-]{1,90}$")
    ml_workspace: str = Field(default="", pattern=r"^[a-zA-Z0-9_-]{0,64}$")
    ml_bootstrap_path: str | None = Field(default=None, pattern=r"^[a-zA-Z0-9_./-]+$")
    region: str = Field(pattern=r"^[a-z0-9]{1,40}$")
    sizes: list[str] = Field(min_length=1, max_length=20)
    default_size: str
    image: str = Field(pattern=r"^[a-zA-Z0-9./:_-]+@sha256:[0-9a-f]{64}$")
    identity: Literal["managed_identity", "azure_cli"] = "managed_identity"
    managed_identity_client_id: str | None = None
    host_identity_resource_id: str | None = None
    host_identity_client_id: str | None = None
    assigned_users: dict[str, str] = Field(default_factory=dict)
    allowed_resources: list[str] = Field(default_factory=list)
    allowed_operations: list[
        Literal["attach", "create", "start", "stop", "reset", "close", "delete"]
    ] = Field(default_factory=lambda: ["attach", "close"])
    managers: list[str] = Field(default_factory=list)
    administrators: list[str] = Field(default_factory=list)
    idle_policy: Literal["manual", "stop"] = "manual"
    max_hosts: int = Field(default=1, ge=1, le=20)
    max_warm_minutes: int = Field(default=60, ge=1, le=120)
    operation_timeout_seconds: int = Field(default=1800, ge=60, le=7200)
    workspace_root: str = "/var/lib/agentbot/workspaces"
    storage_policy: Literal["persistent_host_disk", "managed_data_disk", "export_before_delete"] = (
        "persistent_host_disk"
    )
    memory_mb: int = Field(default=2048, ge=512, le=32768)
    cpu_count: int = Field(default=1, ge=1, le=8)
    subnet_id: str | None = None
    ssh_public_key: str | None = None
    vm_image: dict[str, str] = Field(
        default_factory=lambda: {
            "publisher": "Canonical",
            "offer": "ubuntu-24_04-lts",
            "sku": "server",
            "version": "latest",
        }
    )
    data_disk_gb: int = Field(default=64, ge=32, le=2048)
    bootstrap_url: str | None = None
    bootstrap_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    package_url: str | None = None
    package_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    key_vault_url: str | None = None
    backend_url: str | None = None

    @model_validator(mode="after")
    def policy(self):
        if self.default_size not in self.sizes:
            raise ValueError("Default size must be allowlisted")
        if self.provider == "azure_ml_compute_instance" and not self.ml_workspace:
            raise ValueError("ML workspace is required")
        path = PurePosixPath(self.workspace_root)
        if (
            not path.is_absolute()
            or ".." in path.parts
            or str(path) in {"/", "/home", "/var"}
            or str(path).startswith(("/tmp", "/mnt", "/home/azureuser"))
        ):
            raise ValueError("Use a dedicated directory on persistent storage")
        if self.idle_policy == "stop" and "stop" not in self.allowed_operations:
            raise ValueError("Idle stop requires stop permission")
        if "delete" in self.allowed_operations and not self.administrators:
            raise ValueError("Resource deletion requires named administrators")
        for url in (
            self.bootstrap_url,
            self.package_url,
            self.key_vault_url,
            self.backend_url,
        ):
            if url and (
                not url.startswith("https://")
                or "@" in url.split("/", 3)[2]
                or "?" in url
                or "#" in url
            ):
                raise ValueError("Profile URLs must use HTTPS without credentials or query secrets")
        if "create" in self.allowed_operations:
            if "stop" not in self.allowed_operations:
                raise ValueError(
                    "Managed creation requires permission to stop retained hosts during cleanup"
                )
            if self.provider == "azure_ml_compute_instance" and not self.ml_bootstrap_path:
                raise ValueError(
                    "Managed ML requires an operator-installed workspace bootstrap script path"
                )
            if not all(
                (
                    self.bootstrap_url,
                    self.bootstrap_sha256,
                    self.package_url,
                    self.package_sha256,
                    self.key_vault_url,
                    self.backend_url,
                    self.host_identity_resource_id,
                    self.host_identity_client_id,
                )
            ):
                raise ValueError(
                    "Managed creation needs pinned bootstrap/package URLs, Key Vault, backend and host identity"
                )
            if self.provider == "azure_vm" and not (self.subnet_id and self.ssh_public_key):
                raise ValueError("VM creation requires an approved subnet and SSH public key")
            if self.provider == "azure_vm" and self.storage_policy != "managed_data_disk":
                raise ValueError("Managed VMs require a dedicated persistent data disk")
            if (
                self.provider == "azure_vm"
                and self.vm_image.get("version", "latest").lower() == "latest"
            ):
                raise ValueError("Managed VMs require an explicit approved OS image version")
        return self

    def resource(self, resource_id):
        prefix = (
            f"/subscriptions/{self.subscription_id}/resourceGroups/{self.resource_group}/providers/"
        )
        suffix = (
            f"Microsoft.MachineLearningServices/workspaces/{self.ml_workspace}/computes/"
            if self.provider == "azure_ml_compute_instance"
            else "Microsoft.Compute/virtualMachines/"
        )
        expected = prefix + suffix
        if not isinstance(resource_id, str) or not resource_id.lower().startswith(expected.lower()):
            raise ValueError("Resource is outside the approved profile")
        name = resource_id[len(expected) :]
        if not re.fullmatch(r"[a-zA-Z0-9_-]{1,64}", name):
            raise ValueError("Invalid Azure compute resource ID")
        return expected + name

    def attached_resource(self, resource_id):
        canonical = self.resource(resource_id)
        if canonical.lower() not in {
            self.resource(item).lower() for item in self.allowed_resources
        }:
            raise ValueError("This resource is not in the operator's attachment allowlist")
        return canonical

    def public(self):
        return {
            "id": self.id,
            "name": self.name,
            "provider": self.provider,
            "region": self.region,
            "sizes": self.sizes,
            "default_size": self.default_size,
            "allowed_operations": self.allowed_operations,
            "resources": self.allowed_resources,
            "storage_policy": self.storage_policy,
            "idle_policy": self.idle_policy,
            "max_hosts": self.max_hosts,
            "max_warm_minutes": self.max_warm_minutes,
        }


def load_profiles(store):
    source = os.getenv("CONTROL_COMPUTE_PROFILES")
    if not source:
        return {}
    path = Path(source)
    if path.stat().st_size > 1024 * 1024:
        raise ValueError("Compute profile file is too large")
    values = json.loads(path.read_text(encoding="utf-8"))
    profiles = [ComputeProfile.model_validate(value) for value in values]
    if len({p.id for p in profiles}) != len(profiles):
        raise ValueError("Duplicate compute profile")
    with store.transaction() as db:
        db.execute("UPDATE compute_profiles SET enabled=0")
        for profile in profiles:
            db.execute(
                "INSERT INTO compute_profiles(id,workspace_id,provider,name,revision,config,enabled) VALUES (?,?,?,?,1,?,NOT EXISTS(SELECT 1 FROM workspaces WHERE id=? AND deleted_at IS NOT NULL)) ON CONFLICT(id) DO UPDATE SET workspace_id=excluded.workspace_id,provider=excluded.provider,name=excluded.name,revision=compute_profiles.revision+1,config=excluded.config,enabled=excluded.enabled",
                (
                    profile.id,
                    profile.workspace_id,
                    profile.provider,
                    profile.name,
                    profile.model_dump_json(),
                    profile.workspace_id,
                ),
            )
    return {p.id: p for p in profiles}
