from __future__ import annotations

import json

from deploy.azure_infra.constants import (
    IMAGE_OFFER,
    IMAGE_PUBLISHER,
    IMAGE_SKU,
    SANDBOX_REPOSITORY,
    WORKSPACE_TAG,
)
from deploy.azure_infra.profiles import (
    choose_manifest_digest,
    normalize_digest,
    pick_image_version,
    pinned_sandbox_image,
)


def tagged_workspace(tags):
    if not isinstance(tags, dict):
        return None
    value = tags.get(WORKSPACE_TAG)
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def workspace_from_groups(groups, resource_group):
    preferred = None
    found = {}
    for group in groups:
        value = tagged_workspace(group.get("tags"))
        if not value:
            continue
        found.setdefault(value, []).append(group.get("name"))
        if str(group.get("name", "")).lower() == resource_group.lower():
            preferred = value
    if preferred:
        return preferred
    if len(found) == 1:
        return next(iter(found))
    if len(found) > 1:
        details = ", ".join(
            f"{name}={workspace_id}" for workspace_id, names in found.items() for name in names
        )
        raise SystemExit(f"Multiple {WORKSPACE_TAG} tags ({details}). Pass --workspace-id.")
    return None


def discover_workspace_id(az, resource_group):
    listed = az.run(["group", "list", "-o", "json"])
    return workspace_from_groups(json.loads(listed.stdout), resource_group)


def discover_sandbox_image(az, acr_name=None):
    listed = az.run(["acr", "list", "-o", "json"], check=False)
    if listed.returncode != 0:
        return None
    registries = json.loads(listed.stdout)
    if acr_name:
        registries = [
            item for item in registries if str(item.get("name", "")).lower() == acr_name.lower()
        ]
    for registry in registries:
        name = registry.get("name")
        login = registry.get("loginServer")
        if not name or not login:
            continue
        repos = az.run(["acr", "repository", "list", "--name", name, "-o", "json"], check=False)
        if repos.returncode != 0:
            continue
        names = json.loads(repos.stdout)
        if not isinstance(names, list) or SANDBOX_REPOSITORY not in names:
            continue
        meta = az.run(
            [
                "acr",
                "manifest",
                "list-metadata",
                "--registry",
                name,
                "--name",
                SANDBOX_REPOSITORY,
                "-o",
                "json",
            ],
            check=False,
        )
        digest = None
        if meta.returncode == 0:
            payload = json.loads(meta.stdout)
            digest = choose_manifest_digest(payload if isinstance(payload, list) else [])
        if not digest:
            shown = az.run(
                [
                    "acr",
                    "repository",
                    "show",
                    "--name",
                    name,
                    "--image",
                    f"{SANDBOX_REPOSITORY}:latest",
                    "-o",
                    "json",
                ],
                check=False,
            )
            if shown.returncode == 0:
                digest = normalize_digest(json.loads(shown.stdout).get("digest"))
        image = pinned_sandbox_image(login, digest)
        if image:
            return image
    return None


def workspace_tag_command(subscription, group, workspace_id):
    resource_id = f"/subscriptions/{subscription}/resourceGroups/{group}"
    return [
        "tag",
        "update",
        "--resource-id",
        resource_id,
        "--operation",
        "Merge",
        "--tags",
        f"{WORKSPACE_TAG}={workspace_id}",
    ]


def require_explicit_version(version):
    if not version or version.lower() == "latest":
        raise SystemExit(
            "The VM image version must be an explicit Ubuntu 24.04 version, not latest."
        )
    return version


def resolve_image_version(az, requested):
    if requested:
        return require_explicit_version(requested)
    listed = az.run(
        [
            "vm",
            "image",
            "list",
            "--publisher",
            IMAGE_PUBLISHER,
            "--offer",
            IMAGE_OFFER,
            "--sku",
            IMAGE_SKU,
            "--all",
            "--query",
            "[].version",
            "-o",
            "json",
        ]
    )
    return pick_image_version(json.loads(listed.stdout))
