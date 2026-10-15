"""Import receipts and transaction-local credential validation."""

import sqlite3

from agentbot_control.common import stamp
from agentbot_control.store import CatalogError, _owned_check


def find(db: sqlite3.Connection, owner: str, request_id: str) -> sqlite3.Row | None:
    return db.execute(
        "SELECT * FROM workflow_import_receipts WHERE owner_id=? AND request_id=?",
        (owner, request_id),
    ).fetchone()


def save(
    db: sqlite3.Connection,
    owner: str,
    request_id: str,
    digest: str,
    version: str,
    workspace: str,
    result: str,
) -> None:
    db.execute(
        "INSERT INTO workflow_import_receipts VALUES (?,?,?,?,?,?,?)",
        (owner, request_id, digest, version, workspace, result, stamp()),
    )


def credential(db: sqlite3.Connection, owner: str, credential_id: str, framework: str) -> None:
    row = db.execute(
        "SELECT provider FROM credentials WHERE id=? AND owner_id=?",
        (credential_id, owner),
    ).fetchone()
    if not row:
        raise CatalogError("Choose an existing API key you own.")
    _owned_check(row["provider"], framework)
