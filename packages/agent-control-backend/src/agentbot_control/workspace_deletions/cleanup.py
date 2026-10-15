"""Bounded cleanup of recorded local files after logical deletion commits."""

import asyncio
import re
from pathlib import Path

from agentbot_control.db import Database
from agentbot_control.repositories.workspace_cleanup import CleanupRecords


class Cleanup:
    def __init__(self, database: Database, blobs: Path, sessions: Path) -> None:
        self.database, self.blobs, self.sessions = database, blobs, sessions
        self.wake = asyncio.Event()
        self.records = CleanupRecords(database)
        self.roots = {root: root.resolve() for root in (blobs, blobs / "artifacts", sessions)}

    def unlink(self, root: Path, name: str) -> None:
        path = root / name
        if (
            root.resolve() != self.roots[root]
            or root.is_symlink()
            or path.is_symlink()
            or path.resolve().parent != self.roots[root]
        ):
            raise OSError("Unsafe cleanup path")
        path.unlink(missing_ok=True)

    def remove(self, kind: str, rid: str) -> None:
        if kind == "artifact" and re.fullmatch(r"blob_[a-f0-9]{32}", rid):
            self.unlink(self.blobs / "artifacts", rid)
        elif kind == "capture" and re.fullmatch(r"capture_[a-f0-9]{32}", rid):
            self.unlink(self.blobs, rid)
            self.unlink(self.blobs, rid + ".tmp")
        elif kind == "session" and re.fullmatch(r"[a-f0-9]{16}", rid):
            self.unlink(self.sessions, rid + ".json")
            self.unlink(self.sessions, rid + ".json.tmp")
        else:
            raise OSError("Invalid cleanup identity")

    def sweep(self) -> bool:
        staging = self.records.staging()
        for item in staging:
            if not re.fullmatch(
                r"staging-transfer_[a-f0-9]{32}-[a-zA-Z0-9_-]+", item["staging_name"]
            ):
                continue
            try:
                self.unlink(self.blobs / "artifacts", item["staging_name"])
            except OSError:
                continue
            self.records.staged_removed(item["id"])
        rows = self.records.pending()
        for row in rows:
            error = None
            try:
                self.remove(row["kind"], row["resource_id"])
            except OSError as exc:
                error = type(exc).__name__
            self.records.settled(row, error)
        return bool(rows)

    async def loop(self, progressed) -> None:
        while True:
            # One worker owns physical deletion. Drain it before releasing the process lock.
            await self.database.offload(self.sweep)
            progressed("workspace_cleanup")
            try:
                await asyncio.wait_for(self.wake.wait(), timeout=1)
            except TimeoutError:
                pass
            self.wake.clear()
