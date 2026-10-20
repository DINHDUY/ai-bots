"""Current membership gates every read, mutation, search hit, and selected share."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agentbot_control.event_store import EventStore
    from agentbot_control.store import Catalog


import json
from datetime import UTC, datetime, timedelta
from typing import Literal

from fastapi import HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field

from agentbot_control.auth import COOKIE_NAME
from agentbot_control.capture_retention import CapturePolicy
from agentbot_control.event_store import identifier, packed, stamp
from agentbot_control.repositories.workspace_cleanup import recovery_workspace
from agentbot_control.schemas import Conflict
from agentbot_control.store import Bot
from agentbot_control.transport import body


class WorkspaceName(BaseModel):
    name: str = Field(min_length=1, max_length=100)


class Member(BaseModel):
    username: str
    role: Literal["operator", "viewer", "remove"]


class Grant(BaseModel):
    username: str
    enabled: bool


class Share(BaseModel):
    username: str
    session_id: str | None = None
    surfaces: list[Literal["browser", "desktop"]] = Field(default_factory=list, max_length=2)
    artifacts: list[str] = Field(default_factory=list, max_length=20)
    hours: int = Field(default=24, ge=1, le=168)


class Preferences(BaseModel):
    revision: int = Field(ge=0)
    workspace_id: str | None = None
    avatar: str = Field(default="", max_length=50)
    display_role: str = Field(default="", max_length=80)
    order: list[str] = Field(default_factory=list, max_length=200)
    folders: dict[str, str] = Field(default_factory=dict, max_length=200)
    read_cursors: dict[str, int] = Field(default_factory=dict, max_length=200)
    onboarding: Literal["new", "completed", "dismissed"] = "new"


class ReadCursor(BaseModel):
    sequence: int = Field(ge=0)


class Workspaces:
    def __init__(self, store: EventStore, catalog: Catalog) -> None:
        self.store, self.catalog = store, catalog

    def user(self, request):
        user = self.catalog.user_from_token(request.cookies.get(COOKIE_NAME))
        if not user:
            raise HTTPException(401, "Sign in required.")
        return user

    def role(self, user_id, wid, owner=False):
        with self.store.transaction() as db:
            row = db.execute(
                "SELECT m.role FROM workspace_members m JOIN workspaces w ON w.id=m.workspace_id WHERE m.workspace_id=? AND m.user_id=? AND w.deleted_at IS NULL",
                (wid, user_id),
            ).fetchone()
        if not row or (owner and row[0] != "owner"):
            raise HTTPException(404, "Workspace unavailable.")
        return row[0]

    def recovery_owner(self, user_id: str, wid: str) -> bool:
        """Only inventory reconciliation may access a deleted workspace."""
        row = recovery_workspace(self.store.database, wid)
        if row and row["deleted_at"]:
            if row["owner_id"] != user_id:
                raise HTTPException(404, "Workspace unavailable.")
            return True
        self.role(user_id, wid)
        return False

    def bot(self, user_id, bot_id, operation="read"):
        with self.store.transaction() as db:
            row = db.execute(
                "SELECT b.*,m.role,s.workspace_id FROM bots b JOIN bot_streams s ON s.bot_id=b.id JOIN workspace_members m ON m.workspace_id=s.workspace_id AND m.user_id=? WHERE b.id=?",
                (user_id, bot_id),
            ).fetchone()
            grant = db.execute(
                "SELECT 1 FROM execution_grants WHERE bot_id=? AND user_id=?",
                (bot_id, user_id),
            ).fetchone()
        if not row:
            raise HTTPException(404, "Bot not found.")
        if row["framework"] in {"ufo", "open_interface"} and row["owner_id"] != user_id:
            raise HTTPException(
                403, "This Windows desktop and its history are private to its owner."
            )
        if operation == "write" and row["owner_id"] != user_id:
            with self.store.transaction() as db:
                cloud = db.execute(
                    "SELECT provider FROM cloud_compute_config WHERE bot_id=?", (bot_id,)
                ).fetchone()
            if cloud and cloud[0] == "azure_ml_compute_instance":
                raise HTTPException(
                    403, "Azure ML Compute Instances are restricted to their mapped owner."
                )
        if operation == "owner" and row["owner_id"] != user_id:
            raise HTTPException(
                403, "Only the bot owner can manage credentials, policies, and Autopilot."
            )
        if (
            operation == "write"
            and row["owner_id"] != user_id
            and not (row["role"] == "operator" and grant)
        ):
            raise HTTPException(
                403,
                "Credential-backed execution requires the owner's explicit bot grant.",
            )
        return Bot(**{k: row[k] for k in Bot.__dataclass_fields__})

    def recipient(self, username):
        with self.store.transaction() as db:
            row = db.execute(
                "SELECT id FROM users WHERE lower(username)=lower(?)", (username,)
            ).fetchone()
        if not row:
            raise HTTPException(404, "Registered recipient not found.")
        return row[0]

    def list_bots(self, user_id, wid=None):
        with self.store.transaction() as db:
            ids = [
                r[0]
                for r in db.execute(
                    "SELECT s.bot_id FROM bot_streams s JOIN bots b ON b.id=s.bot_id JOIN workspace_members m ON m.workspace_id=s.workspace_id WHERE m.user_id=? AND (b.framework NOT IN ('ufo','open_interface') OR b.owner_id=?) AND (? IS NULL OR s.workspace_id=?)",
                    (user_id, user_id, wid, wid),
                )
            ]
        return [self.bot(user_id, bid) for bid in ids]

    def share(self, user_id, share_id):
        with self.store.transaction() as db:
            row = db.execute(
                "SELECT * FROM share_grants WHERE id=? AND recipient_id=? AND revoked=0 AND expires_at>?",
                (share_id, user_id, stamp()),
            ).fetchone()
        if not row:
            raise HTTPException(404, "Share expired or unavailable.")
        return dict(row)

    def project(self, db, event):
        if event["type"] not in {
            "approval.pending",
            "approval.required",
            "run.completed",
            "run.failed",
            "run.finished",
            "routine.completed",
            "routine.failed",
            "lifecycle.idle_warning",
            "lifecycle.failed",
            "handoff.completed",
            "handoff.failed",
        }:
            return
        for member in db.execute(
            "SELECT user_id FROM workspace_members WHERE workspace_id=?",
            (event["workspace_id"],),
        ).fetchall():
            db.execute(
                "INSERT OR IGNORE INTO notifications(id,user_id,bot_id,event_id,kind,created_at) VALUES (?,?,?,?,?,?)",
                (
                    identifier("notice"),
                    member[0],
                    event["bot_id"],
                    event["event_id"],
                    event["type"],
                    event["occurred_at"],
                ),
            )


def register_workspace_routes(app):
    return http.register_workspace_routes(app)


from agentbot_control.workspaces import http

__all__ = [
    "BaseModel",
    "Bot",
    "COOKIE_NAME",
    "CapturePolicy",
    "Conflict",
    "Field",
    "FileResponse",
    "Grant",
    "HTTPException",
    "Literal",
    "Member",
    "Preferences",
    "ReadCursor",
    "Request",
    "Share",
    "StreamingResponse",
    "TYPE_CHECKING",
    "UTC",
    "WorkspaceName",
    "Workspaces",
    "body",
    "datetime",
    "http",
    "identifier",
    "json",
    "packed",
    "register_workspace_routes",
    "stamp",
    "timedelta",
]
