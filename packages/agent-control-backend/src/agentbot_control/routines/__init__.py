"""Transactional occurrence claims; all dispatch goes through the runtime arbiter."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agentbot_control.autopilot import Autopilot
    from agentbot_control.channels import Channels
    from agentbot_control.event_store import EventStore
    from agentbot_control.groups import Groups
    from agentbot_control.lifecycle import Lifecycle
    from agentbot_control.policies import Policies
    from agentbot_control.ports import StartRun, StopRun
    from agentbot_control.store import Catalog
    from agentbot_control.toolkit import Toolkit
    from agentbot_control.workspaces import Workspaces

import hashlib
import hmac
import json
import logging
import re
import secrets
import time
from datetime import UTC, datetime, timedelta
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import HTTPException, Request
from pydantic import BaseModel, Field, model_validator

from agentbot_control.event_store import identifier, packed, sanitized, stamp
from agentbot_control.groups import GroupTask
from agentbot_control.lifecycle import LifecycleCommand
from agentbot_control.schemas import Command, Conflict
from agentbot_control.store import CatalogError, User
from agentbot_control.toolkit import ConnectorCall
from agentbot_control.transport import body

logger = logging.getLogger("AgentBotRoutines")


class RoutineDefinition(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    bot_id: str | None = None
    group_id: str | None = None
    prompt: str = Field(default="", max_length=16000)
    skill_id: str | None = None
    connection_id: str | None = None
    connector_operation: Literal["list_issues", "create_issue"] = "list_issues"
    parameters: dict[str, str] = Field(default_factory=dict, max_length=20)
    approval_policy_id: str | None = None
    trigger: Literal["manual", "interval", "daily", "webhook", "event"] = "manual"
    interval_seconds: int = Field(default=3600, ge=60, le=2592000)
    timezone: str = "UTC"
    local_time: str = Field(default="09:00", pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    missed: Literal["skip", "latest"] = "skip"
    overlap: Literal["skip", "queue"] = "skip"
    event: Literal["run.completed", "artifact.retained"] = "run.completed"
    enabled: bool = True
    resume_computer: bool = False
    timeout_seconds: int = Field(default=300, ge=30, le=900)
    version: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def validate_target(self):
        if bool(self.bot_id) == bool(self.group_id):
            raise ValueError("Select one bot or one group")
        if self.group_id and (self.skill_id or self.connection_id):
            raise ValueError("Group routines use explicit mentioned prompts")
        if self.group_id and (self.trigger == "event" or self.approval_policy_id):
            raise ValueError(
                "Group routines use manual, time, or webhook triggers with each bot's explicit human approvals"
            )
        if self.skill_id and self.connection_id:
            raise ValueError("Select one reusable tool")
        if not self.prompt and not (self.skill_id or self.connection_id):
            raise ValueError("Prompt required")
        try:
            ZoneInfo(self.timezone)
        except ZoneInfoNotFoundError:
            raise ValueError("Unknown IANA timezone")
        return self


def next_time(definition, after):
    if definition.trigger == "interval":
        return after + timedelta(seconds=definition.interval_seconds)
    if definition.trigger != "daily":
        return None
    zone = ZoneInfo(definition.timezone)
    hour, minute = map(int, definition.local_time.split(":"))
    local = after.astimezone(zone)
    for day in range(370):
        date = local.date() + timedelta(days=day)
        candidate = datetime(date.year, date.month, date.day, hour, minute, tzinfo=zone, fold=0)
        utc = candidate.astimezone(UTC)
        # Nonexistent spring-forward times are skipped, fall-back uses the first fold only.
        if utc > after and utc.astimezone(zone).replace(tzinfo=None) == candidate.replace(
            tzinfo=None
        ):
            return utc
    raise Conflict("No valid schedule occurrence within a year.")


def latest_due(definition, due, now):
    """Coalesce missed occurrences without shifting the original schedule."""
    if definition.trigger == "interval":
        elapsed = (now - due).total_seconds()
        return due + timedelta(
            seconds=(elapsed // definition.interval_seconds) * definition.interval_seconds
        )
    if definition.trigger == "daily":
        candidate = next_time(definition, now - timedelta(days=3))
        while candidate <= now:
            due = max(due, candidate)
            candidate = next_time(definition, candidate)
    return due


class Routines:
    def __init__(
        self,
        store: EventStore,
        *,
        accepting: Callable[[], bool],
        autopilot: Autopilot,
        catalog: Catalog,
        channels: Channels,
        groups: Groups,
        lifecycle: Lifecycle,
        policies: Policies,
        start: StartRun,
        stop: StopRun,
        toolkit: Toolkit,
        workspace_features: bool,
        workspaces: Workspaces,
    ) -> None:
        self.store = store
        self.accepting = accepting
        self.autopilot = autopilot
        self.catalog = catalog
        self.channels = channels
        self.groups = groups
        self.lifecycle = lifecycle
        self.policies = policies
        self.start = start
        self.stop = stop
        self.toolkit = toolkit
        self.workspace_features = workspace_features
        self.workspaces = workspaces

    def get(self, uid, rid, owner=False):
        with self.store.transaction() as db:
            row = db.execute(
                "SELECT r.*,v.definition FROM routines r JOIN routine_versions v ON v.routine_id=r.id AND v.version=r.version WHERE r.id=? AND r.deleted=0",
                (rid,),
            ).fetchone()
        if not row:
            raise HTTPException(404, "Routine not found.")
        self.workspaces.role(uid, row["workspace_id"], owner=owner)
        return dict(row)

    def authorize(self, uid, wid, definition, *, check_policy=True):
        if definition.bot_id:
            bot = self.workspaces.bot(uid, definition.bot_id, "write")
            with self.store.transaction() as db:
                actual = db.execute(
                    "SELECT workspace_id FROM bot_streams WHERE bot_id=?", (bot.id,)
                ).fetchone()[0]
            if actual != wid:
                raise Conflict("Routine target belongs to another workspace.")
            if not self.catalog.open_model_config(bot.owner_id, bot):
                raise Conflict("Routine target has no model credential.")
            if definition.skill_id:
                self.toolkit.program(uid, bot.id, definition.skill_id, definition.parameters)
            if definition.connection_id:
                self.toolkit.connection(bot.id, definition.connection_id)
            if (
                check_policy
                and definition.approval_policy_id
                and not self.autopilot.state(bot.id)["enabled"]
            ):
                policies = self.policies.list(bot.id)
                if not any(
                    p["id"] == definition.approval_policy_id
                    and p.get("revoked_at") is None
                    and p["expires_at"] > stamp()
                    for p in policies
                ):
                    raise Conflict("Routine approval policy expired or revoked.")
        else:
            group = self.groups.get(uid, definition.group_id, True)
            if group["workspace_id"] != wid:
                raise Conflict("Routine group belongs to another workspace.")
            for bid in group["bot_ids"]:
                self.workspaces.bot(uid, bid, "write")

    def claim(self, routine, occurrence, data=None):
        with self.store.transaction() as db:
            current = db.execute(
                "SELECT * FROM routines WHERE id=? AND deleted=0 AND enabled=1 AND version=?",
                (routine["id"], routine["version"]),
            ).fetchone()
            if not current:
                raise Conflict("Routine paused, changed, or deleted.", code="human_control")
            previous = db.execute(
                "SELECT * FROM routine_jobs WHERE routine_id=? AND version=? AND occurrence=?",
                (routine["id"], routine["version"], occurrence),
            ).fetchone()
            if previous:
                return dict(previous)
            queued = db.execute(
                "SELECT COUNT(*) FROM routine_jobs j JOIN routines r ON r.id=j.routine_id WHERE r.workspace_id=? AND j.state IN ('claimed','running')",
                (current["workspace_id"],),
            ).fetchone()[0]
            if queued >= 64:
                raise Conflict("Workspace routine queue limit reached (64 jobs).")
            jid = identifier("job")
            now = stamp()
            db.execute(
                "INSERT OR IGNORE INTO routine_jobs VALUES (?,?,?,?,'claimed',NULL,NULL,NULL,?,?,?,NULL)",
                (
                    jid,
                    routine["id"],
                    routine["version"],
                    occurrence,
                    packed(sanitized(data or {})),
                    now,
                    now,
                ),
            )
            row = db.execute(
                "SELECT * FROM routine_jobs WHERE routine_id=? AND version=? AND occurrence=?",
                (routine["id"], routine["version"], occurrence),
            ).fetchone()
        return dict(row)

    async def dispatch(self, job):
        return await dispatching.dispatch(self, job)

    async def tick(self):
        now = datetime.now(UTC)
        with self.store.transaction() as db:
            rows = db.execute(
                "SELECT r.*,v.definition FROM routines r JOIN routine_versions v ON v.routine_id=r.id AND v.version=r.version WHERE r.enabled=1 AND r.deleted=0 LIMIT 500"
            ).fetchall()
        for row in rows:
            definition = RoutineDefinition.model_validate_json(row["definition"])
            if row["next_at"] and row["next_at"] <= now.isoformat():
                first_due = datetime.fromisoformat(row["next_at"])
                due = latest_due(definition, first_due, now)
                if definition.missed == "latest" or (now - first_due).total_seconds() < 60:
                    try:
                        self.claim(row, "time:" + due.isoformat())
                    except Conflict:
                        # Leave the occurrence due for a later bounded retry.
                        continue
                upcoming = next_time(definition, due)
                with self.store.transaction() as db:
                    db.execute(
                        "UPDATE routines SET next_at=? WHERE id=? AND version=?",
                        (
                            upcoming.isoformat() if upcoming else None,
                            row["id"],
                            row["version"],
                        ),
                    )
            if definition.trigger == "event" and definition.bot_id:
                with self.store.transaction() as db:
                    events = db.execute(
                        "SELECT e.seq AS cursor,e.envelope FROM bot_events e WHERE e.bot_id=? AND e.seq>? ORDER BY e.seq LIMIT 100",
                        (definition.bot_id, row["event_cursor"]),
                    ).fetchall()
                for item in events:
                    event = json.loads(item["envelope"])
                    # Routine and handoff output cannot re-trigger event routines: depth is capped at one.
                    run = (
                        self.store.run(definition.bot_id, event["run_id"])
                        if event.get("run_id")
                        else None
                    )
                    if (
                        (
                            event["type"] == definition.event
                            or (
                                definition.event == "run.completed"
                                and event["type"] == "run.finished"
                                and event["data"].get("status") == "completed"
                            )
                        )
                        and run
                        and run["trigger"] not in {"routine", "handoff"}
                    ):
                        self.claim(
                            row,
                            "event:" + event["event_id"],
                            {
                                "event_id": event["event_id"],
                                "correlation_id": event["run_id"],
                                "depth": 1,
                            },
                        )
                    with self.store.transaction() as db:
                        db.execute(
                            "UPDATE routines SET event_cursor=? WHERE id=?",
                            (item["cursor"], row["id"]),
                        )
        with self.store.transaction() as db:
            jobs = [
                dict(r)
                for r in db.execute(
                    "SELECT * FROM routine_jobs WHERE state IN ('claimed','running') ORDER BY created_at LIMIT 100"
                )
            ]
        for job in jobs:
            await self.dispatch(job)

    async def loop(self):
        while True:
            if self.accepting() and self.workspace_features:
                try:
                    await self.groups.tick()
                    await self.tick()
                    self.store.health.progressed("routines")
                except Exception:
                    logger.exception("Automation dispatch failed; durable jobs retained")
            else:
                self.store.health.progressed("routines")
            await asyncio.sleep(1)


def register_routine_routes(app):
    return http.register_routine_routes(app)


from agentbot_control.routines import dispatching, http

__all__ = [
    "BaseModel",
    "Callable",
    "CatalogError",
    "Command",
    "Conflict",
    "ConnectorCall",
    "Field",
    "GroupTask",
    "HTTPException",
    "LifecycleCommand",
    "Literal",
    "Request",
    "RoutineDefinition",
    "Routines",
    "TYPE_CHECKING",
    "UTC",
    "User",
    "ZoneInfo",
    "ZoneInfoNotFoundError",
    "asyncio",
    "body",
    "datetime",
    "dispatching",
    "hashlib",
    "hmac",
    "http",
    "identifier",
    "json",
    "latest_due",
    "logger",
    "logging",
    "model_validator",
    "next_time",
    "packed",
    "re",
    "register_routine_routes",
    "sanitized",
    "secrets",
    "stamp",
    "time",
    "timedelta",
]
