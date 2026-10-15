"""Workspace peer messaging: published directory, durable inbox and continuations.

All dispatch uses the original human principal and ordinary runtime admission.
Channel writes and admission bookkeeping share the EventStore transaction.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agentbot_control.event_store import EventStore
    from agentbot_control.files import Files
    from agentbot_control.ports import StartRun, StopRun
    from agentbot_control.store import Bot, Catalog
    from agentbot_control.tool_libraries import ToolLibraries
    from agentbot_control.workspaces import Workspaces

import hashlib
import json
import logging
from datetime import UTC, datetime, timedelta
from typing import Literal

from agentbot.execution import RunYield as PeerWait
from agentbot_tools.messaging import bind_peer_tools, peer_schemas
from agentbot_tools.registry import REGISTRY
from fastapi import HTTPException, Request, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, ConfigDict, Field

from agentbot_control.auth import COOKIE_NAME
from agentbot_control.event_store import (
    fingerprint,
    identifier,
    packed,
    protected,
    sanitized,
    stamp,
)
from agentbot_control.schemas import ACTIVE_RUNS, Command, Conflict
from agentbot_control.store import User
from agentbot_control.transport import body

log = logging.getLogger(__name__)
LIBRARY = "workspace.messaging"
TOOL = "workspace_messaging"
OPEN = ("open", "waiting_peer")
PENDING = ("queued", "blocked")


class ChannelConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision: int = Field(ge=0)
    enabled: bool
    enroll_bot_ids: list[str] = Field(default_factory=list, max_length=200)
    enroll_future: bool = False


class Participation(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    revision: int = Field(ge=0)
    enabled: bool
    purpose: str = Field(default="", max_length=400)
    expires_at: datetime | None = None


class ChannelPost(Command):
    kind: Literal["request", "update"] = "request"
    recipient_id: str | None = None
    thread_id: str | None = None
    text: str = Field(min_length=1, max_length=8192)
    requires_computer: bool = False
    artifact_ids: list[str] = Field(default_factory=list, max_length=5)


class ReadCursor(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sequence: int = Field(ge=0)


def bounded(value, limit=8192):
    if not isinstance(value, str) or not value.strip() or len(value.encode()) > limit:
        raise Conflict(f"Text must be nonblank and fit {limit} UTF-8 bytes.")
    return sanitized(value.strip())


class Channels:
    def __init__(
        self,
        store: EventStore,
        *,
        accepting: Callable[[], bool],
        catalog: Catalog,
        ensure: Callable[[Bot], None],
        files: Files,
        start: StartRun,
        stop: StopRun,
        tools: ToolLibraries,
        workspaces: Workspaces,
        enabled: bool,
    ) -> None:
        self.store = store
        self.accepting = accepting
        self.catalog = catalog
        self.ensure = ensure
        self.files = files
        self.start = start
        self.stop = stop
        self.tools = tools
        self.workspaces = workspaces
        self.enabled = enabled

    def available(self):
        if not self.enabled:
            raise HTTPException(404, "Workspace bot channels are disabled.")

    def _channel(self, db, wid):
        return access._channel(self, db, wid)

    def _role(self, db, uid, wid, *, write=False, owner=False):
        return access._role(self, db, uid, wid, write=write, owner=owner)

    def _authorize(self, db, uid, bid, wid):
        return access._authorize(self, db, uid, bid, wid)

    def event(self, db, wid, kind, data, *, directory=False):
        return access.event(self, db, wid, kind, data, directory=directory)

    def sync_bot(self, db, bot):
        return membership.sync_bot(self, db, bot)

    def binding_changed(self, db, bid):
        return membership.binding_changed(self, db, bid)

    def _has_bundle(self, db, bid):
        return access._has_bundle(self, db, bid)

    def _retire(self, db, row, state, kind):
        return membership._retire(self, db, row, state, kind)

    def retire(self, db, bid, *, final=False):
        return membership.retire(self, db, bid, final=final)

    def expire(self, db):
        return membership.expire(self, db)

    def _participant(self, db, bid, wid, generation=None):
        return access._participant(self, db, bid, wid, generation)

    def enroll(self, db, bid, uid, command):
        return membership.enroll(self, db, bid, uid, command)

    def creation(self, db, bot, join=None):
        return membership.creation(self, db, bot, join)

    def configure(self, uid, wid, command):
        return membership.configure(self, uid, wid, command)

    def participation(self, uid, bid):
        return membership.participation(self, uid, bid)

    def _directory(self, db, wid, query="", offset=0):
        return conversation._directory(self, db, wid, query, offset)

    def directory(self, uid, wid, query="", offset=0):
        return conversation.directory(self, uid, wid, query, offset)

    def _messages(self, db, wid, thread_id=None, before=0):
        return conversation._messages(self, db, wid, thread_id, before)

    def snapshot(self, uid, wid):
        return conversation.snapshot(self, uid, wid)

    def _new_thread(self, db, wid, uid, bid=None, rid=None):
        return conversation._new_thread(self, db, wid, uid, bid, rid)

    def _thread(self, db, tid, wid, uid):
        return conversation._thread(self, db, tid, wid, uid)

    def _context(self, db, bid, rid):
        return conversation._context(self, db, bid, rid)

    def _post(
        self,
        db,
        wid,
        uid,
        kind,
        text,
        key,
        *,
        tid=None,
        source=None,
        rid=None,
        recipient=None,
        reply_to=None,
        mode="communication",
        depth=0,
        artifact_ids=(),
    ):
        return publication._post(
            self,
            db,
            wid,
            uid,
            kind,
            text,
            key,
            tid=tid,
            source=source,
            rid=rid,
            recipient=recipient,
            reply_to=reply_to,
            mode=mode,
            depth=depth,
            artifact_ids=artifact_ids,
        )

    def post(self, uid, wid, command):
        return publication.post(self, uid, wid, command)

    def _artifact(self, db, wid, uid, aid):
        return publication._artifact(self, db, wid, uid, aid)

    def _artifact_context(self, db, wid, mid):
        return publication._artifact_context(self, db, wid, mid)

    def _wait(self, db, run, source, context, thread, args):
        return binding._wait(self, db, run, source, context, thread, args)

    def bind(self, bid, rid, streamer, context):
        return binding.bind(self, bid, rid, streamer, context)

    def _cancel(self, db, tid, state="cancelled"):
        return admission_ops._cancel(self, db, tid, state)

    def cancel(self, uid, wid, tid):
        return admission_ops.cancel(self, uid, wid, tid)

    def stop_bot(self, bid, rid=None):
        return admission_ops.stop_bot(self, bid, rid)

    def user_admitted(self, db, bid):
        return admission_ops.user_admitted(self, db, bid)

    def valid_run(self, db, rid):
        return admission_ops.valid_run(self, db, rid)

    def task(self, uid, bid):
        return admission_ops.task(self, uid, bid)

    def _valid_delivery(self, db, delivery):
        return admission_ops._valid_delivery(self, db, delivery)

    def admit(self, db, bot, rid, delivery_id):
        return admission_ops.admit(self, db, bot, rid, delivery_id)

    def inherit(self, db, bot, rid, request_id, trigger):
        return admission_ops.inherit(self, db, bot, rid, request_id, trigger)

    def automation_state(self, rid):
        return admission_ops.automation_state(self, rid)

    def _settled(self, db, ids):
        return scheduling._settled(self, db, ids)

    def _fulfill(self, db):
        return scheduling._fulfill(self, db)

    async def tick(self):
        return await scheduling.tick(self)

    async def loop(self):
        return await scheduling.loop(self)

    def events(self, uid, wid, after):
        return scheduling.events(self, uid, wid, after)

    def prune(self, db, cutoff):
        return scheduling.prune(self, db, cutoff)


def register_channel_routes(app):
    return http.register_channel_routes(app)


from agentbot_control.channels import (
    access,
    admission_ops,
    binding,
    conversation,
    http,
    membership,
    publication,
    scheduling,
)

__all__ = [
    "ACTIVE_RUNS",
    "BaseModel",
    "COOKIE_NAME",
    "Callable",
    "ChannelConfig",
    "ChannelPost",
    "Channels",
    "Command",
    "ConfigDict",
    "Conflict",
    "Field",
    "HTTPException",
    "LIBRARY",
    "Literal",
    "OPEN",
    "PENDING",
    "Participation",
    "PeerWait",
    "REGISTRY",
    "ReadCursor",
    "Request",
    "TOOL",
    "TYPE_CHECKING",
    "UTC",
    "User",
    "WebSocket",
    "WebSocketDisconnect",
    "access",
    "admission_ops",
    "asyncio",
    "bind_peer_tools",
    "binding",
    "body",
    "bounded",
    "conversation",
    "datetime",
    "fingerprint",
    "hashlib",
    "http",
    "identifier",
    "json",
    "log",
    "logging",
    "membership",
    "packed",
    "peer_schemas",
    "protected",
    "publication",
    "register_channel_routes",
    "sanitized",
    "scheduling",
    "stamp",
    "timedelta",
]
