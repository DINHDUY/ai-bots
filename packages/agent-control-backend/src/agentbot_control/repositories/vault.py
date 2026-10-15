"""All fields encrypted by Catalog/Policies; hashes are deliberately excluded."""

import sqlite3

from agentbot_control.vault import Vault

SEALED_COLUMNS = (
    ("credentials", "secret"),
    ("connections", "secret"),
    ("routines", "webhook_secret"),
    ("actions", "arguments_sealed"),
    ("approval_policies", "constraints_sealed"),
    ("cloud_operation_state", "continuation_sealed"),
)


def rotate_batch(
    connection: sqlite3.Connection,
    vault: Vault,
    table: str,
    column: str,
    after: int,
    *,
    dry_run: bool = False,
    limit: int = 100,
) -> tuple[int, int, int]:
    if (table, column) not in SEALED_COLUMNS:
        raise ValueError("Unknown encrypted column")
    rows = connection.execute(
        f'SELECT rowid,"{column}" FROM "{table}" WHERE rowid>? AND "{column}" IS NOT NULL ORDER BY rowid LIMIT ?',
        (after, limit),
    ).fetchall()
    changed = 0
    for row_id, token in rows:
        plaintext = vault.unseal(token)  # Validate current records as well as legacy records.
        if not vault.is_current(token):
            changed += 1
            if not dry_run:
                connection.execute(
                    f'UPDATE "{table}" SET "{column}"=? WHERE rowid=?',
                    (vault.seal(plaintext), row_id),
                )
    return (rows[-1][0] if rows else after), len(rows), changed
