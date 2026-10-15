"""Pinned bootstrap references only; enrollment secrets never appear in customData."""

import base64
import json
import shlex


def script(profile, secret_name):
    settings = {
        "backend": profile.backend_url,
        "vault": profile.key_vault_url,
        "secret_name": secret_name,
        "identity_client_id": profile.host_identity_client_id,
        "package_url": profile.package_url,
        "package_sha256": profile.package_sha256,
        "workspace_root": profile.workspace_root,
        "provider": profile.provider,
        "storage_policy": profile.storage_policy,
        "ownership": "managed",
    }
    payload = base64.b64encode(json.dumps(settings).encode()).decode()
    return "\n".join(
        [
            "#!/bin/bash",
            "set -eu",
            "umask 077",
            "install -d -m 700 /etc/agentbot /var/lib/agentbot-host",
            f"printf %s {shlex.quote(payload)} | base64 -d > /etc/agentbot/bootstrap.json",
            f"curl --fail --silent --show-error --proto '=https' --tlsv1.2 {shlex.quote(profile.bootstrap_url)} -o /etc/agentbot/bootstrap.sh",
            f"printf '%s  %s\\n' {shlex.quote(profile.bootstrap_sha256)} /etc/agentbot/bootstrap.sh | sha256sum --check --status",
            "bash /etc/agentbot/bootstrap.sh",
            "",
        ]
    )
