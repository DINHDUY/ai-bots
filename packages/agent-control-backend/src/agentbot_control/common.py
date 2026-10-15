"""Shared helpers with no dependency on the event store or catalog."""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from datetime import UTC, datetime


def stamp():
    return datetime.now(UTC).isoformat()


def identifier(prefix):
    return prefix + "_" + uuid.uuid4().hex


def packed(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def fingerprint(value):
    return hashlib.sha256(packed(value).encode()).hexdigest()


def protected(path):
    name = path.replace("\\", "/").rsplit("/", 1)[-1].lower()
    return (
        name == ".env"
        or name.endswith((".env", ".pem", ".key", ".p12", ".pfx"))
        or name.startswith(".env.")
        or name in {"credentials", "credentials.json", "id_rsa", "id_ed25519"}
    )


def sanitized(value, secrets=()):
    if isinstance(value, dict):
        return {k: sanitized(v, secrets) for k, v in value.items()}
    if isinstance(value, list):
        return [sanitized(v, secrets) for v in value]
    if not isinstance(value, str):
        return value
    for secret in secrets:
        if secret:
            value = value.replace(secret, "[redacted]")
    value = re.sub(r"(https?://)[^\s/@]+:[^\s/@]+@", r"\1[redacted]@", value)
    value = re.sub(
        r"([?&](?:sig|token|api_key|access_token)=)[^&\s]+",
        r"\1[redacted]",
        value,
        flags=re.I,
    )
    return value[:64000]
