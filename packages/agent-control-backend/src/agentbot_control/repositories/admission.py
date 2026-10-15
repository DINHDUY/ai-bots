"""Capacity checks share the transaction that reserves a run or computer."""

from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass

from agentbot_control.schemas import Conflict


@dataclass(frozen=True)
class AdmissionLimits:
    runs: int = 32
    runs_per_owner: int = 8
    computers: int = 64
    computers_per_owner: int = 16

    @classmethod
    def from_environment(cls) -> AdmissionLimits:
        values = {}
        for field, default in (
            ("runs", 32),
            ("runs_per_owner", 8),
            ("computers", 64),
            ("computers_per_owner", 16),
        ):
            name = "CONTROL_MAX_" + field.upper()
            try:
                value = int(os.environ.get(name, str(default)))
            except ValueError:
                raise ValueError(f"{name} must be a positive integer") from None
            if value < 1:
                raise ValueError(f"{name} must be a positive integer")
            values[field] = value
        return cls(**values)


def require_run(db: sqlite3.Connection, bot_id: str, limits: AdmissionLimits) -> None:
    counts = db.execute(
        "SELECT COUNT(*), COALESCE(SUM(b.owner_id=(SELECT owner_id FROM bots WHERE id=?)),0) "
        "FROM runs r JOIN bots b ON b.id=r.bot_id "
        "WHERE r.status IN ('preparing','running','awaiting_approval','stopping')",
        (bot_id,),
    ).fetchone()
    if counts[0] >= limits.runs or counts[1] >= limits.runs_per_owner:
        raise Conflict(
            "Active run capacity reached. Wait for work to finish and retry.", code="capacity_limit"
        )


def require_computer(
    db: sqlite3.Connection,
    bot_id: str | None,
    limits: AdmissionLimits,
    *,
    owner_id: str | None = None,
) -> None:
    # Retained, failed and hibernated computers continue to consume capacity until closed.
    # A workspace-owned computer counts once and is charged to the workspace owner.
    counts = db.execute(
        "SELECT COUNT(*), COALESCE(SUM("
        "CASE WHEN c.bot_id IS NOT NULL THEN b.owner_id=COALESCE((SELECT owner_id FROM bots WHERE id=?), ?) "
        "ELSE w.owner_id=COALESCE((SELECT owner_id FROM bots WHERE id=?), ?) END),0) "
        "FROM computer_sessions c LEFT JOIN bots b ON b.id=c.bot_id "
        "LEFT JOIN workspaces w ON w.id=c.workspace_id WHERE c.status!='closed'",
        (bot_id, owner_id, bot_id, owner_id),
    ).fetchone()
    if counts[0] >= limits.computers or counts[1] >= limits.computers_per_owner:
        raise Conflict(
            "Computer capacity reached. Close an unused computer and retry.", code="capacity_limit"
        )
