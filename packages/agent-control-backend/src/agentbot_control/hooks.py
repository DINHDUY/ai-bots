"""Typed callbacks the event store invokes without importing those subsystems."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from agentbot.tools.context import ToolAccess


class EventProjector(Protocol):
    def project(self, db, event) -> None: ...


class AdmissionHook(Protocol):
    def pin(self, db, bot, rid) -> None: ...

    def valid(self, db, bid, rid, binding_id, revision, digest) -> bool: ...

    def access(self, bid, rid, sandbox) -> ToolAccess: ...


class ChannelHooks(Protocol):
    def user_admitted(self, db, bot_id, /) -> None: ...

    def admit(self, db, bot, rid, channel_delivery_id, /) -> None: ...

    def inherit(self, db, bot, rid, request_id, trigger) -> None: ...

    def valid_run(self, db, run_id, /) -> bool: ...

    def prune(self, db, cutoff) -> None: ...


@dataclass
class StoreHooks:
    projector: EventProjector | None = None
    admission: AdmissionHook | None = None
    channels: ChannelHooks | None = None
