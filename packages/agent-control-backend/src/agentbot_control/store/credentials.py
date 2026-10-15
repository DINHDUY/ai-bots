from __future__ import annotations

import secrets
from typing import TYPE_CHECKING

from agentbot_control.store import (
    CatalogConflict,
    CatalogError,
    Credential,
    _api_key,
    _credential,
    _endpoint,
    _name,
    _owned_check,
    _provider,
    _stamp,
)

if TYPE_CHECKING:
    from agentbot_control.store import Catalog


def create_credential(
    self: Catalog, owner_id: str, provider: str, label: str, api_key: str, endpoint: str = ""
) -> Credential:
    provider = _provider(provider)
    label = _name(label)
    api_key = _api_key(api_key)
    endpoint = _endpoint(provider, endpoint)
    credential_id = secrets.token_hex(8)
    stamp = _stamp(self._now())
    secret = self.seal(api_key.encode("utf-8"))
    with self._lock:
        self._connection.execute(
            """
            INSERT INTO credentials (
                id, owner_id, provider, label, secret, endpoint, key_hint, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                credential_id,
                owner_id,
                provider,
                label,
                secret,
                endpoint,
                api_key[-4:],
                stamp,
                stamp,
            ),
        )
        self._connection.commit()
    credential = self.get_credential(owner_id, credential_id)
    assert credential is not None
    return credential


def list_credentials(self: Catalog, owner_id: str) -> list[Credential]:
    with self._lock:
        rows = self._connection.execute(
            "SELECT * FROM credentials WHERE owner_id = ? ORDER BY created_at, id",
            (owner_id,),
        ).fetchall()
    return [_credential(row) for row in rows]


def get_credential(self: Catalog, owner_id: str, credential_id: str) -> Credential | None:
    with self._lock:
        row = self._connection.execute(
            "SELECT * FROM credentials WHERE id = ? AND owner_id = ?",
            (credential_id, owner_id),
        ).fetchone()
    if row is None:
        return None
    return _credential(row)


def update_credential(
    self: Catalog,
    owner_id: str,
    credential_id: str,
    *,
    label: str | None = None,
    endpoint: str | None = None,
    api_key: str | None = None,
) -> Credential | None:
    current = self.get_credential(owner_id, credential_id)
    if current is None:
        return None
    next_label = current.label if label is None else _name(label)
    next_endpoint = current.endpoint if endpoint is None else _endpoint(current.provider, endpoint)
    next_secret = None
    next_hint = current.key_hint
    if api_key is not None:
        checked = _api_key(api_key)
        next_secret = self.seal(checked.encode("utf-8"))
        next_hint = checked[-4:]
    stamp = _stamp(self._now())
    with self._lock:
        if next_secret is None:
            self._connection.execute(
                """
                UPDATE credentials
                SET label = ?, endpoint = ?, updated_at = ?
                WHERE id = ? AND owner_id = ?
                """,
                (next_label, next_endpoint, stamp, credential_id, owner_id),
            )
        else:
            self._connection.execute(
                """
                UPDATE credentials
                SET label = ?, endpoint = ?, secret = ?, key_hint = ?, updated_at = ?
                WHERE id = ? AND owner_id = ?
                """,
                (
                    next_label,
                    next_endpoint,
                    next_secret,
                    next_hint,
                    stamp,
                    credential_id,
                    owner_id,
                ),
            )
        self._connection.commit()
    return self.get_credential(owner_id, credential_id)


def delete_credential(self: Catalog, owner_id: str, credential_id: str) -> bool:
    current = self.get_credential(owner_id, credential_id)
    if current is None:
        return False
    with self._lock:
        used = self._connection.execute(
            "SELECT 1 FROM bots WHERE credential_id = ? AND owner_id = ?",
            (credential_id, owner_id),
        ).fetchone()
        if used is not None:
            raise CatalogConflict("This key is still used by a bot.")
        self._connection.execute(
            "DELETE FROM credentials WHERE id = ? AND owner_id = ?",
            (credential_id, owner_id),
        )
        self._connection.commit()
    return True


def _owned_credential(
    self: Catalog, owner_id: str, credential_id: str, framework: str
) -> Credential:
    credential = self.get_credential(owner_id, credential_id)
    if credential is None:
        raise CatalogError("API key not found.")
    _owned_check(credential.provider, framework)
    return credential
