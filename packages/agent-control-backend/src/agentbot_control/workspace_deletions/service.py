"""Owner-scoped deletion, atomic persistence, and restart-safe recovery."""

from collections.abc import Callable
from pathlib import Path

from fastapi import HTTPException

from agentbot_control.common import fingerprint
from agentbot_control.db import Database
from agentbot_control.repositories import workspace_deletions as rows
from agentbot_control.repositories.workspace_deletion_commands import commit
from agentbot_control.repositories.workspace_preview import preview
from agentbot_control.workspace_deletions.cleanup import Cleanup
from agentbot_control.workspace_deletions.schemas import (
    DeleteCommand,
    DeletionHistory,
    DeletionPreview,
    DeletionResult,
)


class WorkspaceDeletions:
    def __init__(
        self, database: Database, blobs: Path, sessions: Path, *, enabled: Callable[[], bool]
    ) -> None:
        self.database, self.enabled = database, enabled
        self.cleanup = Cleanup(database, blobs, sessions)

    async def preview(self, owner: str, wid: str) -> DeletionPreview:
        if not self.enabled():
            raise HTTPException(409, "Workspace deletion is unavailable.")
        return await self.database.read(lambda db: preview(db, owner, wid))

    async def delete(self, owner: str, wid: str, command: DeleteCommand) -> DeletionResult:
        digest = fingerprint({"workspace_id": wid, **command.model_dump()})

        result = await self.database.run(
            lambda db: commit(db, owner, wid, command, digest, self.enabled, self.database.changed)
        )
        self.cleanup.wake.set()
        return result

    async def get(self, owner: str, request_id: str) -> DeletionResult:
        return await self.database.read(lambda db: rows.get(db, owner, request_id))

    async def history(self, owner: str, cursor: int) -> DeletionHistory:
        return await self.database.read(lambda db: rows.history(db, owner, cursor))

    async def retry(self, owner: str, request_id: str) -> DeletionResult:
        result = await self.database.run(lambda db: rows.retry(db, owner, request_id))
        self.cleanup.wake.set()
        return result
