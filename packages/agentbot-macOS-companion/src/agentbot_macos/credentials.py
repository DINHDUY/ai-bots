"""Pairing credentials in the user's Keychain; receipt identity survives updates."""

from __future__ import annotations

import json
import os
from pathlib import Path
from urllib.parse import urlsplit


def directory() -> Path:
    path = Path.home() / "Library/Application Support/AgentControl/macOS"
    if path.is_symlink():
        raise ValueError("Companion state directory may not be a symlink")
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(path, 0o700)
    return path


def endpoint(value: str) -> str:
    url = urlsplit(value)
    if (
        not url.hostname
        or url.username
        or url.password
        or url.query
        or url.fragment
        or url.path not in {"", "/"}
    ):
        raise ValueError("Use a backend origin without credentials, path, query or fragment")
    if url.scheme != "https" and not (
        url.scheme == "http" and url.hostname in {"127.0.0.1", "localhost", "::1"}
    ):
        raise ValueError("Remote pairing requires HTTPS")
    return value.rstrip("/")


def query():
    import Security as S

    return {
        S.kSecClass: S.kSecClassGenericPassword,
        S.kSecAttrService: "AgentControl.macOS",
        S.kSecAttrAccount: "companion",
    }


def load() -> dict:
    import Security as S

    status, data = S.SecItemCopyMatching(
        {**query(), S.kSecReturnData: True, S.kSecMatchLimit: S.kSecMatchLimitOne}, None
    )
    if status != 0:
        raise RuntimeError("No accessible Mac pairing; run agentbot-macos pair")
    value = json.loads(bytes(data))
    marker = directory() / "journal.identity"
    if (
        not marker.is_file()
        or marker.is_symlink()
        or marker.read_text() != value["journal_id"]
        or not (directory() / "receipts.sqlite").is_file()
    ):
        raise RuntimeError(
            "Receipt journal identity missing; recover the original journal before reconnecting"
        )
    from agentbot_macos.receipts import ReceiptJournal

    journal = ReceiptJournal(directory() / "receipts.sqlite")
    identity = journal.identity
    journal.close()
    if identity != value["journal_id"]:
        raise RuntimeError("Receipt journal was replaced; recover the original before reconnecting")
    endpoint(value["backend"])
    return value


def save(value: dict) -> None:
    import Foundation
    import Security as S

    from agentbot_macos.receipts import ReceiptJournal

    root = directory()
    marker = root / "journal.identity"
    if marker.is_symlink():
        raise ValueError("Journal identity may not be a symlink")
    journal = ReceiptJournal(root / "receipts.sqlite")
    identity = journal.identity
    journal.close()
    if marker.exists() and marker.read_text() != identity:
        raise RuntimeError("Original receipt journal required before re-pairing")
    marker.write_text(identity)
    os.chmod(marker, 0o600)
    value = {**value, "journal_id": identity}
    raw = json.dumps(value).encode()
    data = Foundation.NSData.dataWithBytes_length_(raw, len(raw))
    item = query()
    status = S.SecItemUpdate(item, {S.kSecValueData: data})
    if status == S.errSecItemNotFound:
        status, _ = S.SecItemAdd({**item, S.kSecValueData: data}, None)
    if status != 0:
        raise RuntimeError("Keychain write failed; pairing token was not persisted")


def forget() -> None:
    import Security as S

    status = S.SecItemDelete(query())
    if status not in {0, S.errSecItemNotFound}:
        raise RuntimeError("Keychain removal failed")
