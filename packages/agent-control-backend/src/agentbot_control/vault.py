"""Versioned encryption envelopes with explicit legacy-key recovery."""

from __future__ import annotations

import base64
import hashlib
import json
import re
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF


class KeyUnavailable(InvalidToken):
    """A required encryption key is absent; never fall back to a different version."""


class Vault:
    def __init__(self, secret: str = "", *, keyring: Path | None = None, legacy_secrets: tuple[str, ...] = ()) -> None:
        self._keys: dict[str, Fernet] = {}
        if keyring is not None:
            try:
                config = json.loads(keyring.read_text(encoding="utf-8"))
                self.active = config["active"]
                for kid, key in config["keys"].items():
                    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", kid):
                        raise ValueError()
                    self._keys[kid] = Fernet(key.encode("ascii"))
                if self.active not in self._keys:
                    raise ValueError()
            except (ValueError, KeyError, TypeError, AttributeError, UnicodeError, OSError):
                raise ValueError("Invalid or unreadable encryption keyring") from None
        else:
            if not secret:
                raise ValueError("An encryption keyring or signing secret is required")
            key = HKDF(algorithm=hashes.SHA256(), length=32, salt=None,
                       info=b"agentbot:encryption:v1").derive(secret.encode("utf-8"))
            self.active = "derived_" + hashlib.sha256(key).hexdigest()[:16]
            self._keys[self.active] = Fernet(base64.urlsafe_b64encode(key))
        # Also retain derived keys when migrating from implicit to explicit keyrings.
        secrets = tuple(dict.fromkeys(value for value in (secret, *legacy_secrets) if value))
        self._legacy = [Fernet(base64.urlsafe_b64encode(hashlib.sha256(value.encode()).digest())) for value in secrets]
        for value in secrets:
            key = HKDF(algorithm=hashes.SHA256(), length=32, salt=None,
                       info=b"agentbot:encryption:v1").derive(value.encode())
            self._keys.setdefault("derived_" + hashlib.sha256(key).hexdigest()[:16], Fernet(base64.urlsafe_b64encode(key)))

    def seal(self, plaintext: bytes) -> str:
        return f"v1:{self.active}:" + self._keys[self.active].encrypt(plaintext).decode("ascii")

    def unseal(self, token: str) -> bytes:
        if token.startswith("v1:"):
            parts = token.split(":", 2)
            if len(parts) != 3 or parts[1] not in self._keys:
                raise KeyUnavailable("Required encryption key is unavailable; restore the matching keyring")
            return self._keys[parts[1]].decrypt(parts[2].encode("ascii"))
        if ":" in token:
            raise KeyUnavailable("Unsupported encryption envelope version")
        for key in self._legacy:
            try:
                return key.decrypt(token.encode("ascii"))
            except InvalidToken:
                continue
        raise KeyUnavailable("Legacy encryption key is unavailable or the record is invalid")

    def is_current(self, token: str) -> bool:
        return token.startswith(f"v1:{self.active}:")
