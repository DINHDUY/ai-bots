"""Reviewed demonstrations and a curated, credential-isolated GitHub runner."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agentbot_control.event_store import EventStore
    from agentbot_control.store import Catalog
    from agentbot_control.workspaces import Workspaces


import asyncio
import json
import re
from typing import Literal

import httpx
from agentbot.interfaces import ActionResult, SandboxError
from fastapi import Request
from pydantic import BaseModel, Field

from agentbot_control.auth import COOKIE_NAME
from agentbot_control.authorization import request_bot
from agentbot_control.control import LeaseCommand
from agentbot_control.event_store import identifier, packed, sanitized, stamp
from agentbot_control.schemas import Command, Conflict
from agentbot_control.transport import body


class RecordingCommand(LeaseCommand):
    operation: Literal["start", "pause", "resume", "stop", "private", "public"]


class SkillDefinition(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=1000)
    recording_id: str
    parameters: dict[str, str] = Field(default_factory=dict, max_length=20)
    steps: list[dict] = Field(max_length=100)


class Replay(Command):
    parameters: dict[str, str] = Field(default_factory=dict, max_length=20)
    resume_paused: bool = False


class ConnectionDefinition(BaseModel):
    repository: str = Field(pattern=r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
    token: str = Field(min_length=10, max_length=512)


class ConnectorCall(Command):
    operation: Literal["list_issues", "create_issue"]
    title: str = Field(default="", max_length=256)
    text: str = Field(default="", max_length=8000)


class Toolkit:
    def __init__(self, store: EventStore, catalog: Catalog, workspaces: Workspaces) -> None:
        self.store, self.catalog, self.workspaces = store, catalog, workspaces
        self.connection_locks = {}

    def bind_tools(self, bid, streamer, context):
        return binding.bind_tools(self, bid, streamer, context)

    def recording(self, lease_id):
        return skills.recording(self, lease_id)

    def record(self, lease_id, event, meta):
        return skills.record(self, lease_id, event, meta)

    def checkpoint(self, lease_id, detail):
        return skills.checkpoint(self, lease_id, detail)

    def skill(self, uid, bid, skill_id):
        return skills.skill(self, uid, bid, skill_id)

    def program(self, uid, bid, skill_id, parameters):
        return skills.program(self, uid, bid, skill_id, parameters)

    def connection(self, bid, cid):
        return connectors.connection(self, bid, cid)

    async def checked_github(self, bid, cid, operation, arguments, expected=None):
        return await connectors.checked_github(self, bid, cid, operation, arguments, expected)

    async def github(self, bid, cid, operation, arguments, expected=None):
        return await connectors.github(self, bid, cid, operation, arguments, expected)

    def connector_program(self, bid, cid, command):
        return connectors.connector_program(self, bid, cid, command)


def register_toolkit_routes(app):
    return http.register_toolkit_routes(app)


from agentbot_control.toolkit import binding, connectors, http, skills

__all__ = [
    "ActionResult",
    "BaseModel",
    "COOKIE_NAME",
    "Command",
    "Conflict",
    "ConnectionDefinition",
    "ConnectorCall",
    "Field",
    "LeaseCommand",
    "Literal",
    "RecordingCommand",
    "Replay",
    "Request",
    "SandboxError",
    "SkillDefinition",
    "TYPE_CHECKING",
    "Toolkit",
    "asyncio",
    "binding",
    "body",
    "connectors",
    "http",
    "httpx",
    "identifier",
    "json",
    "packed",
    "re",
    "register_toolkit_routes",
    "request_bot",
    "sanitized",
    "skills",
    "stamp",
]
