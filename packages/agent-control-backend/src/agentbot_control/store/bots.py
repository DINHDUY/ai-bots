from __future__ import annotations

import secrets
from typing import TYPE_CHECKING

from agentbot.models import (
    ModelConfig,
)
from cryptography.fernet import InvalidToken

from agentbot_control.store import (
    _UNSET,
    Bot,
    CatalogError,
    _bot,
    _default_prompt,
    _instructions,
    _model_name,
    _name,
    _stamp,
)

if TYPE_CHECKING:
    from agentbot_control.store import Catalog


def create_bot(
    self: Catalog,
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
    name = _name(name)
    instructions = _instructions(instructions, preserve=preserve_instructions)
    default_prompt = _default_prompt(default_prompt)
    model = _model_name(model)
    self._owned_credential(owner_id, credential_id, framework)
    bot_id = secrets.token_hex(8)
    stamp = _stamp(self._now())
    with self._bot_write(_db) as db:
        db.execute(
            """
            INSERT INTO bots (
                id, owner_id, name, framework, instructions, credential_id, model, created_at, updated_at, default_prompt
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                bot_id,
                owner_id,
                name,
                framework,
                instructions,
                credential_id,
                model,
                stamp,
                stamp,
                default_prompt,
            ),
        )
    bot = self.get_bot_by_id_tx(_db, bot_id) if _db is not None else self.get_bot(owner_id, bot_id)
    assert bot is not None
    return bot


def list_bots(self: Catalog, owner_id: str) -> list[Bot]:
    with self._lock:
        rows = self._connection.execute(
            "SELECT * FROM bots WHERE owner_id = ? ORDER BY created_at, id",
            (owner_id,),
        ).fetchall()
    return [_bot(row) for row in rows]


def get_bot(self: Catalog, owner_id: str, bot_id: str) -> Bot | None:
    with self._lock:
        row = self._connection.execute(
            "SELECT * FROM bots WHERE id = ? AND owner_id = ?",
            (bot_id, owner_id),
        ).fetchone()
    if row is None:
        return None
    return _bot(row)


def update_bot(
    self: Catalog,
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
    current = (
        self.get_bot_by_id_tx(_db, bot_id) if _db is not None else self.get_bot(owner_id, bot_id)
    )
    if current is None or current.owner_id != owner_id:
        return None
    next_name = current.name if name is None else _name(name)
    next_instructions = (
        current.instructions if instructions is None else _instructions(instructions)
    )
    next_prompt = (
        current.default_prompt if default_prompt is _UNSET else _default_prompt(default_prompt)
    )
    if credential_id is _UNSET and model is _UNSET:
        next_credential = current.credential_id
        next_model = current.model
    else:
        chosen = current.credential_id if credential_id is _UNSET else credential_id
        chosen_model = current.model if model is _UNSET else model
        if not isinstance(chosen, str) or not chosen:
            raise CatalogError("Choose an API key.")
        if not isinstance(chosen_model, str):
            raise CatalogError("Model is required.")
        next_model = _model_name(chosen_model)
        self._owned_credential(owner_id, chosen, current.framework)
        next_credential = chosen
    stamp = _stamp(self._now())
    with self._bot_write(_db) as db:
        db.execute(
            """
            UPDATE bots
            SET name = ?, instructions = ?, credential_id = ?, model = ?, updated_at = ?, default_prompt = ?
            WHERE id = ? AND owner_id = ?
            """,
            (
                next_name,
                next_instructions,
                next_credential,
                next_model,
                stamp,
                next_prompt,
                bot_id,
                owner_id,
            ),
        )
    return self.get_bot_by_id_tx(_db, bot_id) if _db is not None else self.get_bot(owner_id, bot_id)


def open_model_config(self: Catalog, owner_id: str, bot: Bot) -> ModelConfig | None:
    """Decrypt the bot's key. None means the bot has no credential yet."""

    if not bot.credential_id:
        return None
    with self._lock:
        row = self._connection.execute(
            "SELECT provider, secret, endpoint FROM credentials WHERE id = ? AND owner_id = ?",
            (bot.credential_id, owner_id),
        ).fetchone()
    if row is None:
        raise CatalogError("This bot's API key is missing.")
    try:
        api_key = self.unseal(row["secret"]).decode("utf-8")
    except (InvalidToken, UnicodeError) as exc:
        raise CatalogError("Stored API key cannot be read. Add the key again.") from exc
    if not bot.model:
        raise CatalogError("This bot has no model.")
    try:
        return ModelConfig(
            provider=row["provider"],
            api_key=api_key,
            model=bot.model,
            endpoint=row["endpoint"],
        )
    except ValueError as exc:
        raise CatalogError(str(exc)) from exc


def delete_bot(self: Catalog, owner_id: str, bot_id: str, *, _db=None) -> bool:
    if _db is not None:
        return (
            _db.execute("DELETE FROM bots WHERE id=? AND owner_id=?", (bot_id, owner_id)).rowcount
            > 0
        )
    with self._lock:
        cursor = self._connection.execute(
            "DELETE FROM bots WHERE id = ? AND owner_id = ?",
            (bot_id, owner_id),
        )
        self._connection.commit()
    return cursor.rowcount > 0
