"""Workspace capture budgets and a durable, retryable deletion ledger."""

from __future__ import annotations

import asyncio
import json
import re
import sqlite3
from datetime import UTC, datetime, timedelta

from fastapi import HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field, model_validator

from agentbot_control.common import identifier, packed, stamp
from agentbot_control.schemas import Conflict

MAX_IMAGE = 4 * 1024 * 1024
BATCH = 100


class CapturePolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    revision: int = Field(ge=1)
    max_count: int | None = Field(default=None, ge=1, le=1_000_000)
    max_bytes: int | None = Field(default=None, ge=1)
    reserve_percent: int = Field(default=25, ge=1, le=98)
    cleanup_target_percent: int = Field(default=50, ge=1, le=98)
    max_age_seconds: int | None = Field(default=604800, ge=3600, le=315360000)

    @model_validator(mode="after")
    def limits(self):
        if all(v is None for v in (self.max_count, self.max_bytes, self.max_age_seconds)):
            raise ValueError("Enable at least one retention limit.")
        if self.max_bytes is not None:
            if self.cleanup_target_percent >= 100 - self.reserve_percent:
                raise ValueError("Cleanup target must be below the cleanup trigger.")
            if self.max_bytes * self.cleanup_target_percent // 100 < MAX_IMAGE:
                raise ValueError("Cleanup target must accommodate a 4 MiB screenshot.")
        return self


class CaptureRetention:
    def __init__(self, store):
        self.store = store
        self.clock = lambda: datetime.now(UTC)
        self.wake = asyncio.Event()

    def policy(self, db, wid):
        return policy.policy(self, db, wid)

    def usage(self, db, wid):
        return policy.usage(self, db, wid)

    def thresholds(self, p):
        return policy.thresholds(self, p)

    def settings(self, wid):
        return policy.settings(self, wid)

    def validate(self, command):
        return policy.validate(self, command)

    def configure(self, wid, uid, command):
        return policy.configure(self, wid, uid, command)

    def candidates(self, db, wid, p, incoming=0):
        yield from policy.candidates(self, db, wid, p, incoming)

    def preview(self, wid, command):
        return policy.preview(self, wid, command)

    def changed(self, db, bid, ids, reason):
        return cleanup.changed(self, db, bid, ids, reason)

    def mark(self, db, rows):
        return cleanup.mark(self, db, rows)

    def path(self, cid, temporary=False):
        return cleanup.path(self, cid, temporary)

    def delete_pending(self, wid=None):
        return cleanup.delete_pending(self, wid)

    def cleanup(self, wid, incoming=0):
        return cleanup.cleanup(self, wid, incoming)

    def store_image(self, bid, rid, raw, metadata):
        return images.store_image(self, bid, rid, raw, metadata)

    def skipped(self, db, bid, rid, reason):
        return images.skipped(self, db, bid, rid, reason)

    def expiry(self, created, p):
        return images.expiry(self, created, p)

    def history_db(
        self,
        db,
        bid,
        surface=None,
        before=None,
        limit=100,
        before_sequence=None,
        session_id=None,
    ):
        return images.history_db(self, db, bid, surface, before, limit, before_sequence, session_id)

    def read(self, bid, cid):
        # Bounded PNG read under the same lock as unlink avoids FileResponse's
        # check/open race and Windows file sharing violations during streaming.
        return images.read(self, bid, cid)

    def response(self, bid, cid):
        return images.response(self, bid, cid)

    def sweep(self):
        return cleanup.sweep(self)

    def recover(self):
        # Called only during startup, under the deployment process lock.
        return cleanup.recover(self)

    async def loop(self):
        return await cleanup.loop(self)


from agentbot_control.capture_retention import cleanup, images, policy

__all__ = [
    "BaseModel",
    "CapturePolicy",
    "CaptureRetention",
    "ConfigDict",
    "Conflict",
    "Field",
    "HTTPException",
    "Response",
    "UTC",
    "asyncio",
    "cleanup",
    "datetime",
    "identifier",
    "images",
    "json",
    "model_validator",
    "packed",
    "policy",
    "re",
    "sqlite3",
    "stamp",
    "timedelta",
]
