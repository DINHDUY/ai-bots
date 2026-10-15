"""Fetch one-time enrollment from Key Vault using the host's own managed identity."""

import json
from pathlib import Path

import httpx

from .app import enroll


async def bootstrap(path):
    settings = json.loads(Path("/etc/agentbot/bootstrap.json").read_text())
    async with httpx.AsyncClient(timeout=30, trust_env=False) as client:
        result = await client.get(
            "http://169.254.169.254/metadata/identity/oauth2/token",
            headers={"Metadata": "true"},
            params={
                "api-version": "2018-02-01",
                "resource": "https://vault.azure.net",
                "client_id": settings["identity_client_id"],
            },
        )
        if result.status_code != 200:
            raise RuntimeError("Managed identity token unavailable")
        token = result.json()["access_token"]
        result = await client.get(
            settings["vault"].rstrip("/") + "/secrets/" + settings["secret_name"],
            params={"api-version": "7.4"},
            headers={"Authorization": "Bearer " + token},
        )
        if result.status_code != 200:
            raise RuntimeError("Enrollment secret unavailable")
        grant = json.loads(result.json()["value"])
    config = await enroll(
        path, settings["backend"], grant["binding_id"], grant["host_key"], grant["code"]
    )
    # Pull only the approved digest. This is a host operation, outside the workload.
    import asyncio

    import docker

    await asyncio.to_thread(docker.from_env().images.pull, config["profile"]["image"])
