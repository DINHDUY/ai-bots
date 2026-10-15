"""Durable admission of local file writers, including upload staging."""

from contextlib import asynccontextmanager

from agentbot_control.common import identifier
from agentbot_control.db import Database
from agentbot_control.repositories import file_transfers as rows


class FileTransfers:
    def __init__(self, database: Database) -> None:
        self.database = database

    @asynccontextmanager
    async def writer(self, bot_id: str):
        token = identifier("transfer")

        try:
            await self.database.run(lambda db: rows.start(db, token, bot_id))
            yield token
        finally:
            # Drain any admitted database/file writes before exposing the transfer as settled.
            await self.database.run(lambda db: rows.finish(db, token))

    async def staging(self, token: str, filename: str) -> None:
        await self.database.run(lambda db: rows.staging(db, token, filename))
