"""Durable local claims. A crash between claim and receipt must never replay input."""

import json
import os
import sqlite3
import threading
import uuid
from pathlib import Path

from agentbot_macos.actions import Permit
from agentbot_macos.protocol import digest, packed
from agentbot_macos.results import unknown


class ReceiptJournal:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if path.is_symlink():
            raise ValueError("Receipt journal may not be a symlink")
        self.db = sqlite3.connect(path, isolation_level=None, check_same_thread=False)
        os.chmod(path, 0o600)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS receipts(id TEXT PRIMARY KEY, digest TEXT NOT NULL, result TEXT)"
        )
        self.db.execute("CREATE TABLE IF NOT EXISTS identity(id TEXT NOT NULL)")
        if not self.db.execute("SELECT 1 FROM identity").fetchone():
            self.db.execute("INSERT INTO identity VALUES (?)", (uuid.uuid4().hex,))
        self.identity = self.db.execute("SELECT id FROM identity").fetchone()[0]
        self.lock = threading.RLock()

    def claim(self, permit: Permit) -> dict | None:
        fingerprint = digest(
            {
                k: permit.model_dump()[k]
                for k in ("device_id", "run_id", "session_id", "generation", "action")
            }
        )
        with self.lock:
            self.db.execute("BEGIN IMMEDIATE")
            try:
                row = self.db.execute(
                    "SELECT digest,result FROM receipts WHERE id=?", (permit.action_id,)
                ).fetchone()
                if row:
                    if row[0] != fingerprint:
                        raise ValueError("Action ID reused with different arguments")
                    result = (
                        json.loads(row[1])
                        if row[1]
                        else unknown("Previous dispatch requires reconciliation; do not replay")
                    )
                else:
                    self.db.execute(
                        "INSERT INTO receipts VALUES (?,?,NULL)", (permit.action_id, fingerprint)
                    )
                    result = None
                self.db.execute("COMMIT")
                return result
            except BaseException:
                self.db.execute("ROLLBACK")
                raise

    def status(self, action_id: str) -> dict:
        with self.lock:
            row = self.db.execute("SELECT result FROM receipts WHERE id=?", (action_id,)).fetchone()
            if row is None:
                return {"found": False}
            return {
                "found": True,
                "result": json.loads(row[0]) if row[0] else unknown("Dispatch outcome unknown"),
            }

    def finish(self, action_id: str, result: dict) -> None:
        with self.lock:
            self.db.execute(
                "UPDATE receipts SET result=? WHERE id=? AND result IS NULL",
                (packed(result), action_id),
            )

    def close(self) -> None:
        with self.lock:
            self.db.close()
