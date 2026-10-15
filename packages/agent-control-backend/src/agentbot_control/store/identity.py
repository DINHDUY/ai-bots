from __future__ import annotations

import secrets
import sqlite3
from typing import TYPE_CHECKING

from agentbot_control.auth import (
    hash_password,
    sign_session,
    unsign_session,
    verify_password,
)
from agentbot_control.store import (
    _DUMMY_HASH,
    SESSION_TTL,
    CatalogError,
    User,
    _password,
    _stamp,
    _username,
)

if TYPE_CHECKING:
    from agentbot_control.store import Catalog


def register(self: Catalog, username: str, password: str) -> tuple[User, str]:
    username = _username(username)
    _password(password)
    user_id = secrets.token_hex(8)
    created = _stamp(self._now())
    password_hash = hash_password(password)
    with self._lock:
        try:
            self._connection.execute(
                "INSERT INTO users (id, username, password_hash, created_at) VALUES (?, ?, ?, ?)",
                (user_id, username, password_hash, created),
            )
            self._connection.commit()
        except sqlite3.IntegrityError as exc:
            raise CatalogError("That username is already taken.") from exc
    return self._open_session(User(user_id, username))


def login(self: Catalog, username: str, password: str) -> tuple[User, str]:
    username = username.strip()
    with self._lock:
        row = self._connection.execute(
            "SELECT id, username, password_hash FROM users WHERE lower(username) = lower(?)",
            (username,),
        ).fetchone()
    valid = verify_password(password, row["password_hash"] if row else _DUMMY_HASH)
    if row is None or not valid:
        raise CatalogError("Invalid username or password.")
    return self._open_session(User(row["id"], row["username"]))


def logout(self: Catalog, token: str | None) -> None:
    session_id = self._session_id(token)
    if session_id is None:
        return
    with self._lock:
        self._connection.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
        self._connection.commit()


def user_from_token(self: Catalog, token: str | None) -> User | None:
    session_id = self._session_id(token)
    if session_id is None:
        return None
    now = _stamp(self._now())
    with self._lock:
        row = self._connection.execute(
            """
            SELECT users.id, users.username, sessions.expires_at
            FROM sessions JOIN users ON users.id = sessions.user_id
            WHERE sessions.id = ?
            """,
            (session_id,),
        ).fetchone()
        if row is None:
            return None
        if row["expires_at"] <= now:
            self._connection.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
            self._connection.commit()
            return None
    return User(row["id"], row["username"])


def _open_session(self: Catalog, user: User) -> tuple[User, str]:
    session_id = secrets.token_hex(16)
    expires = _stamp(self._now() + SESSION_TTL)
    with self._lock:
        self._connection.execute(
            "INSERT INTO sessions (id, user_id, expires_at) VALUES (?, ?, ?)",
            (session_id, user.id, expires),
        )
        self._connection.commit()
    return user, sign_session(session_id, self._secret)


def _session_id(self: Catalog, token: str | None) -> str | None:
    if not token:
        return None
    return unsign_session(token, self._secret)
