"""Offline maintenance under the same deployment lock as the control process."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from agentbot_control.db import Database
from agentbot_control.process_lock import ProcessLock
from agentbot_control.repositories.vault import SEALED_COLUMNS, rotate_batch
from agentbot_control.vault import Vault


async def rotate(database: Database, vault: Vault, *, dry_run: bool = False) -> dict[str, int]:
    counts = {"verified": 0, "rotation_candidates": 0}
    for table, column in SEALED_COLUMNS:
        after = 0
        while True:
            def batch(db):
                return rotate_batch(db, vault, table, column, after, dry_run=dry_run)
            after, read, changed = await (database.read(batch) if dry_run else database.run(batch))
            counts["verified"] += read
            counts["rotation_candidates"] += changed
            if read == 0:
                break
    return counts


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["rotate-keys"])
    parser.add_argument("--database", required=True, type=Path)
    parser.add_argument("--keyring", required=True, type=Path)
    parser.add_argument("--legacy-secret-file", action="append", type=Path, default=[])
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if not args.database.is_file():
        parser.error("Database must already exist")
    vault = Vault(keyring=args.keyring, legacy_secrets=tuple(p.read_text(encoding="utf-8").strip() for p in args.legacy_secret_file))
    lock = ProcessLock(args.database.with_suffix(".runtime.lock"))
    lock.acquire()
    try:
        database = Database(args.database, migrate=False)
        try:
            result = asyncio.run(rotate(database, vault, dry_run=args.dry_run))
            print(json.dumps({"dry_run": args.dry_run, "active_key": vault.active, **result}))
        finally:
            database.close()
    finally:
        lock.release()


if __name__ == "__main__":
    main()
