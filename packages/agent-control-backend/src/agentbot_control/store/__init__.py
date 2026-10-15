"""SQLite catalog of users, login sessions, and owned bots."""

from __future__ import annotations

import os
import re
import secrets
import sqlite3
from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from agentbot.models import (
    ModelConfig,
    providers_for_framework,
    validate_foundry_endpoint,
)
from cryptography.fernet import InvalidToken

from agentbot_control.auth import (
    hash_password,
    sign_session,
    unsign_session,
    verify_password,
)
from agentbot_control.db import CatalogConnection, Database
from agentbot_control.vault import Vault

_DUMMY_HASH = "scrypt$16384$8$1$" + "00" * 16 + "$" + "00" * 64
SESSION_TTL = timedelta(days=7)
_USERNAME = re.compile(r"^[A-Za-z0-9_-]{3,32}$")


class CatalogError(Exception):
    """A catalog write was rejected."""


class CatalogConflict(CatalogError):
    """The write conflicts with a row that still depends on it."""


_UNSET = object()
_PROVIDERS = frozenset({"openai", "anthropic", "azure_foundry"})


@dataclass(frozen=True)
class User:
    id: str
    username: str


@dataclass(frozen=True)
class Bot:
    id: str
    owner_id: str
    name: str
    framework: str
    instructions: str
    credential_id: str | None
    model: str
    created_at: str
    updated_at: str
    default_prompt: str = ""


@dataclass(frozen=True)
class Credential:
    id: str
    owner_id: str
    provider: str
    label: str
    endpoint: str
    key_hint: str
    created_at: str
    updated_at: str


class Catalog:
    """One SQLite file for the control-plane process."""

    def __init__(self, path: Path, secret: str, *, now=None) -> None:
        if not secret:
            raise ValueError("AGENTBOT_SECRET is required.")
        self._bot_authorizer: Callable[[str, str, str], Bot | None] | None = None
        self._secret = secret
        self._now = now or (lambda: datetime.now(UTC))
        self.db = Database(path)
        self._lock = self.db.lock
        self._connection = CatalogConnection(self.db)
        keyring = os.getenv("AGENTBOT_KEYRING_FILE")
        self.vault = Vault(secret, keyring=Path(keyring) if keyring else None)

    def configure_authorization(self, authorize: Callable[[str, str, str], Bot | None]) -> None:
        self._bot_authorizer = authorize

    def authorized_bot(self, user_id: str, bot_id: str, operation: str = "read") -> Bot | None:
        if self._bot_authorizer is not None:
            return self._bot_authorizer(user_id, bot_id, operation)
        return self.get_bot(user_id, bot_id)

    def seal(self, plaintext: bytes) -> str:
        return self.vault.seal(plaintext)

    def unseal(self, token: str) -> bytes:
        return self.vault.unseal(token)

    def close(self) -> None:
        self.db.close()

    def register(self, username: str, password: str) -> tuple[User, str]:
        return identity.register(self, username, password)

    def login(self, username: str, password: str) -> tuple[User, str]:
        return identity.login(self, username, password)

    def logout(self, token: str | None) -> None:
        return identity.logout(self, token)

    def user_from_token(self, token: str | None) -> User | None:
        return identity.user_from_token(self, token)

    def create_credential(
        self,
        owner_id: str,
        provider: str,
        label: str,
        api_key: str,
        endpoint: str = "",
    ) -> Credential:
        return credentials.create_credential(self, owner_id, provider, label, api_key, endpoint)

    def list_credentials(self, owner_id: str) -> list[Credential]:
        return credentials.list_credentials(self, owner_id)

    def get_credential(self, owner_id: str, credential_id: str) -> Credential | None:
        return credentials.get_credential(self, owner_id, credential_id)

    def update_credential(
        self,
        owner_id: str,
        credential_id: str,
        *,
        label: str | None = None,
        endpoint: str | None = None,
        api_key: str | None = None,
    ) -> Credential | None:
        return credentials.update_credential(
            self, owner_id, credential_id, label=label, endpoint=endpoint, api_key=api_key
        )

    def delete_credential(self, owner_id: str, credential_id: str) -> bool:
        return credentials.delete_credential(self, owner_id, credential_id)

    @contextmanager
    def _bot_write(self, db=None):
        if db is not None:
            yield db
        else:
            with self._lock, self._connection:
                yield self._connection

    @staticmethod
    def get_bot_by_id_tx(db, bot_id):
        row = db.execute("SELECT * FROM bots WHERE id=?", (bot_id,)).fetchone()
        return _bot(row) if row else None

    def create_bot(
        self,
        owner_id: str,
        name: str,
        framework: str,
        instructions: str,
        credential_id: str,
        model: str,
        default_prompt: str = "",
        _db=None,
        *,
        preserve_instructions: bool = False,
    ) -> Bot:
        return bots.create_bot(
            self,
            owner_id,
            name,
            framework,
            instructions,
            credential_id,
            model,
            default_prompt,
            _db,
            preserve_instructions=preserve_instructions,
        )

    def list_bots(self, owner_id: str) -> list[Bot]:
        return bots.list_bots(self, owner_id)

    def get_bot(self, owner_id: str, bot_id: str) -> Bot | None:
        return bots.get_bot(self, owner_id, bot_id)

    def update_bot(
        self,
        owner_id: str,
        bot_id: str,
        *,
        name: str | None = None,
        instructions: str | None = None,
        credential_id: str | None | object = _UNSET,
        model: str | None | object = _UNSET,
        default_prompt: str | object = _UNSET,
        _db=None,
    ) -> Bot | None:
        return bots.update_bot(
            self,
            owner_id,
            bot_id,
            name=name,
            instructions=instructions,
            credential_id=credential_id,
            model=model,
            default_prompt=default_prompt,
            _db=_db,
        )

    def open_model_config(self, owner_id: str, bot: Bot) -> ModelConfig | None:
        return bots.open_model_config(self, owner_id, bot)

    def _owned_credential(self, owner_id: str, credential_id: str, framework: str) -> Credential:
        return credentials._owned_credential(self, owner_id, credential_id, framework)

    def delete_bot(self, owner_id: str, bot_id: str, *, _db=None) -> bool:
        return bots.delete_bot(self, owner_id, bot_id, _db=_db)

    def _open_session(self, user: User) -> tuple[User, str]:
        return identity._open_session(self, user)

    def _session_id(self, token: str | None) -> str | None:
        return identity._session_id(self, token)


def _stamp(moment: datetime) -> str:
    return moment.astimezone(UTC).isoformat()


def _username(value: str) -> str:
    username = value.strip()
    if not _USERNAME.fullmatch(username):
        raise CatalogError("Username must be 3-32 characters of letters, digits, '_' or '-'.")
    return username


def _password(value: str) -> None:
    if not isinstance(value, str) or len(value) < 8 or len(value) > 128:
        raise CatalogError("Password must be 8-128 characters.")


def _name(value: str) -> str:
    name = value.strip()
    if not name or len(name) > 80:
        raise CatalogError("Name must be 1-80 characters.")
    return name


def _instructions(value: str, *, preserve: bool = False) -> str:
    text = value if preserve else value.strip()
    if len(text) > 16000:
        raise CatalogError("Instructions must be 16000 characters or fewer.")
    return text


def _default_prompt(value: object) -> str:
    if not isinstance(value, str):
        raise CatalogError("Default prompt must be text.")
    text = value.strip()
    if len(text) > 8000:
        raise CatalogError("Default prompt must be 8000 characters or fewer.")
    return text


def _bot(row: sqlite3.Row) -> Bot:
    return Bot(
        id=row["id"],
        owner_id=row["owner_id"],
        name=row["name"],
        framework=row["framework"],
        instructions=row["instructions"],
        credential_id=row["credential_id"],
        model=row["model"] or "",
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        default_prompt=row["default_prompt"],
    )


def _credential(row: sqlite3.Row) -> Credential:
    return Credential(
        id=row["id"],
        owner_id=row["owner_id"],
        provider=row["provider"],
        label=row["label"],
        endpoint=row["endpoint"] or "",
        key_hint=row["key_hint"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _provider(value: str) -> str:
    provider = value.strip().lower()
    if provider not in _PROVIDERS:
        raise CatalogError("Provider must be openai, anthropic, or azure_foundry.")
    return provider


def _api_key(value: str) -> str:
    key = value.strip()
    if len(key) < 8 or len(key) > 4096 or any(char in key for char in "\r\n"):
        raise CatalogError("API key must be 8-4096 characters on one line.")
    return key


def _endpoint(provider: str, value: str) -> str:
    text = value.strip()
    if provider != "azure_foundry":
        if text:
            raise CatalogError("Only an azure_foundry credential uses an endpoint.")
        return ""
    try:
        return validate_foundry_endpoint(text)
    except ValueError as exc:
        raise CatalogError(str(exc)) from exc


def _model_name(value: str) -> str:
    model = value.strip()
    if not re.fullmatch(r"[A-Za-z0-9._:/-]{1,128}", model):
        raise CatalogError("Model must be 1-128 characters of letters, digits, or . _ : / -.")
    return model


def _owned_check(provider: str, framework: str) -> None:
    allowed = providers_for_framework(framework)
    if allowed is not None and provider not in allowed:
        raise CatalogError(f"Framework '{framework}' cannot use a {provider} key.")


from agentbot_control.store import bots, credentials, identity

__all__ = [
    "Bot",
    "Callable",
    "Catalog",
    "CatalogConflict",
    "CatalogConnection",
    "CatalogError",
    "Credential",
    "Database",
    "InvalidToken",
    "ModelConfig",
    "Path",
    "UTC",
    "User",
    "Vault",
    "bots",
    "contextmanager",
    "credentials",
    "dataclass",
    "datetime",
    "hash_password",
    "identity",
    "os",
    "providers_for_framework",
    "re",
    "secrets",
    "sign_session",
    "sqlite3",
    "timedelta",
    "unsign_session",
    "validate_foundry_endpoint",
    "verify_password",
]
