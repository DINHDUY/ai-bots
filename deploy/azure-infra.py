"""Provision the Azure attach pilot and write compute-profiles.json.

Reads the example profile, fills tenant, subscription, owner, and resource IDs
from Azure CLI, and on --apply creates only the missing resource group, ML
workspace, private subnet, ML compute instance, and Linux VM. Dry-run is the
default. The control backend still does not create those resources itself.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

"""Stable public exports for the separated domain modules."""

from deploy.azure_infra.cli import main as main
from deploy.azure_infra.cli import manual_steps as manual_steps
from deploy.azure_infra.cli import parse_args as parse_args
from deploy.azure_infra.commands import Az as Az
from deploy.azure_infra.commands import AzError as AzError
from deploy.azure_infra.commands import az_executable as az_executable
from deploy.azure_infra.commands import control_username as control_username
from deploy.azure_infra.commands import display as display
from deploy.azure_infra.commands import is_missing as is_missing
from deploy.azure_infra.commands import ml_resource_id as ml_resource_id
from deploy.azure_infra.commands import show as show
from deploy.azure_infra.commands import subnet_resource_id as subnet_resource_id
from deploy.azure_infra.commands import subscription_of as subscription_of
from deploy.azure_infra.commands import vm_resource_id as vm_resource_id
from deploy.azure_infra.commands import with_arm_id as with_arm_id
from deploy.azure_infra.constants import ADMIN_USERNAME as ADMIN_USERNAME
from deploy.azure_infra.constants import ATTACH as ATTACH
from deploy.azure_infra.constants import DEFAULT_OUTPUT as DEFAULT_OUTPUT
from deploy.azure_infra.constants import ENV_KEY as ENV_KEY
from deploy.azure_infra.constants import EXAMPLE as EXAMPLE
from deploy.azure_infra.constants import IMAGE_OFFER as IMAGE_OFFER
from deploy.azure_infra.constants import IMAGE_PUBLISHER as IMAGE_PUBLISHER
from deploy.azure_infra.constants import IMAGE_SKU as IMAGE_SKU
from deploy.azure_infra.constants import ROOT as ROOT
from deploy.azure_infra.constants import SANDBOX_REPOSITORY as SANDBOX_REPOSITORY
from deploy.azure_infra.constants import SUBNET_PREFIX as SUBNET_PREFIX
from deploy.azure_infra.constants import USERNAME as USERNAME
from deploy.azure_infra.constants import VNET_PREFIX as VNET_PREFIX
from deploy.azure_infra.constants import WORKSPACE_TAG as WORKSPACE_TAG
from deploy.azure_infra.discovery import discover_sandbox_image as discover_sandbox_image
from deploy.azure_infra.discovery import discover_workspace_id as discover_workspace_id
from deploy.azure_infra.discovery import require_explicit_version as require_explicit_version
from deploy.azure_infra.discovery import resolve_image_version as resolve_image_version
from deploy.azure_infra.discovery import tagged_workspace as tagged_workspace
from deploy.azure_infra.discovery import workspace_from_groups as workspace_from_groups
from deploy.azure_infra.discovery import workspace_tag_command as workspace_tag_command
from deploy.azure_infra.profiles import choose_manifest_digest as choose_manifest_digest
from deploy.azure_infra.profiles import fill_profiles as fill_profiles
from deploy.azure_infra.profiles import format_env_value as format_env_value
from deploy.azure_infra.profiles import ml_compute_yaml as ml_compute_yaml
from deploy.azure_infra.profiles import normalize_digest as normalize_digest
from deploy.azure_infra.profiles import pick_image_version as pick_image_version
from deploy.azure_infra.profiles import pinned_sandbox_image as pinned_sandbox_image
from deploy.azure_infra.profiles import set_env_assignment as set_env_assignment
from deploy.azure_infra.profiles import validate_profiles as validate_profiles
from deploy.azure_infra.profiles import version_key as version_key
from deploy.azure_infra.profiles import write_env as write_env
from deploy.azure_infra.profiles import write_profiles as write_profiles
from deploy.azure_infra.provisioning import ensure_group as ensure_group
from deploy.azure_infra.provisioning import ensure_ml_compute as ensure_ml_compute
from deploy.azure_infra.provisioning import ensure_ml_extension as ensure_ml_extension
from deploy.azure_infra.provisioning import ensure_network as ensure_network
from deploy.azure_infra.provisioning import ensure_ssh_key as ensure_ssh_key
from deploy.azure_infra.provisioning import ensure_vm as ensure_vm
from deploy.azure_infra.provisioning import ensure_workspace as ensure_workspace
from deploy.azure_infra.provisioning import nic_resource_id as nic_resource_id
from deploy.azure_infra.provisioning import public_key_path as public_key_path

if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except AzError as exc:
        raise SystemExit(f"Azure CLI failed: {exc}") from exc
