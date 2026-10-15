"""Local stop and durable at-most-once dispatch receipts; no Windows imports."""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path

from .protocol import Permit, digest, packed


class LocalState:
    def __init__(self):
        self.lock = threading.RLock()
        self.sharing = False
        self.armed = False
        self.hand_off = False
        self.revision = 0
        self.reason = "Sharing is off"
        self.last_contact = time.monotonic()

    def change(self, *, sharing=None, armed=None, reason=""):
        with self.lock:
            if sharing is not None:
                self.sharing = bool(sharing)
            if armed is not None:
                self.armed = bool(armed)
            if not self.sharing:
                self.armed = False
            self.reason = reason
            self.revision += 1

    def stop(self, reason="Stopped locally"):
        self.change(armed=False, reason=reason)

    def set_hand_off(self, enabled):
        # Local input preference only; preserve permissions and in-flight permits.
        with self.lock:
            self.hand_off = bool(enabled)

    def should_pause_on_input(self, automating):
        with self.lock:
            return self.armed and automating and not self.hand_off

    def check(self, *, write=False):
        with self.lock:
            if time.monotonic() - self.last_contact > 15:
                self.stop("Backend connection lost")
            if not self.sharing or (write and not self.armed):
                raise RuntimeError(self.reason or "Local sharing/control is off")
            return self.revision


class ReceiptJournal:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, isolation_level=None, check_same_thread=False)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS receipts(id TEXT PRIMARY KEY, digest TEXT NOT NULL, result TEXT)"
        )
        self.lock = threading.Lock()

    def claim(self, permit: Permit):
        fingerprint = digest(
            {
                "session": permit.session_id,
                "generation": permit.generation,
                "action": permit.action.model_dump(),
            }
        )
        with self.lock:
            row = self.db.execute(
                "SELECT digest,result FROM receipts WHERE id=?", (permit.action_id,)
            ).fetchone()
            if row:
                if row[0] != fingerprint:
                    raise RuntimeError("Action ID reused with different arguments")
                return (
                    json.loads(row[1])
                    if row[1]
                    else {
                        "ok": False,
                        "outcome_unknown": True,
                        "text": "Previous dispatch outcome is unknown; do not replay",
                    }
                )
            self.db.execute(
                "INSERT INTO receipts VALUES (?,?,NULL)",
                (permit.action_id, fingerprint),
            )
        return None

    def finish(self, action_id, result):
        with self.lock:
            self.db.execute(
                "UPDATE receipts SET result=? WHERE id=? AND result IS NULL",
                (packed(result), action_id),
            )

    def close(self):
        self.db.close()
