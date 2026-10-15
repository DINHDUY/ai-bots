"""Persisted, bounded authentication admission windows."""

import hashlib
import sqlite3
from collections.abc import Sequence


def key(kind: str, value: str) -> str:
    return kind + ":" + hashlib.sha256(value.casefold().encode()).hexdigest()


def reserve(db: sqlite3.Connection, limits: Sequence[tuple[str, int, float]], now: float) -> int:
    db.execute("DELETE FROM auth_limits WHERE expires<=?", (now,))
    retry = 0
    for name, maximum, _ in limits:
        row = db.execute("SELECT attempts,expires FROM auth_limits WHERE key=?", (name,)).fetchone()
        if row and row[0] >= maximum:
            retry = max(retry, int(row[1] - now) + 1)
    if retry:
        return retry
    if db.execute("SELECT COUNT(*) FROM auth_limits").fetchone()[0] >= 20000:
        return 60
    for name, _, window in limits:
        db.execute(
            "INSERT INTO auth_limits VALUES (?,1,?) ON CONFLICT(key) DO UPDATE SET attempts=attempts+1",
            (name, now + window),
        )
    return 0


def clear_account(db: sqlite3.Connection, name: str) -> None:
    db.execute("DELETE FROM auth_limits WHERE key=?", (name,))
