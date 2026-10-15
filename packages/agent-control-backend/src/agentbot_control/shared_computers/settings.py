"""Workspace computer mode. Owners change it only while every eligible computer is closed."""

from __future__ import annotations

import json
from typing import Literal

from pydantic import Field

from agentbot_control.common import fingerprint, stamp
from agentbot_control.repositories.workspace_computers import initialize_shared_docker
from agentbot_control.schemas import Command, Conflict
from agentbot_control.shared_computers.resolution import (
    blocking,
    open_computer,
    present,
    settings_row,
)


class UpdateComputer(Command):
    expected_revision: int = Field(ge=0)
    mode: Literal["per_bot", "shared"]
    provider: str = "docker"
    profile_id: str | None = None
    ownership: Literal["attached", "managed"] = "attached"


def initialize_shared(db, workspace_id: str, owner: str) -> None:
    """Initialize a newly created workspace in the caller's transaction."""
    if settings_row(db, workspace_id)["revision"] or blocking(db, workspace_id):
        raise Conflict("Shared initialization requires a new workspace.")
    initialize_shared_docker(db, workspace_id, owner)


def view(store, workspace_id, role):
    with store.transaction() as db:
        settings = settings_row(db, workspace_id)
        computer = open_computer(db, workspace_id) or _latest(db, workspace_id)
        shown = present(computer, db)
    return {
        **settings,
        "role": role,
        "computer": shown,
        "attached_bot_ids": (shown or {}).get("attached_bot_ids", []),
        "busy": False if not computer else _busy(store, computer["id"]),
        "limitation": (
            "Overlapping runs share the desktop, browser, files, and processes. "
            "Individual actions run one at a time."
        ),
    }


def _latest(db, workspace_id):
    row = db.execute(
        "SELECT * FROM computer_sessions WHERE workspace_id=? ORDER BY generation DESC LIMIT 1",
        (workspace_id,),
    ).fetchone()
    return dict(row) if row else None


def _busy(store, sid) -> bool:
    from agentbot_control.shared_computers.resolution import session_busy_store

    return session_busy_store(store, sid)


def update(store, cloud, workspace_id, user_id, command: UpdateComputer):
    digest = fingerprint(command.model_dump())

    def write():
        with store.transaction() as db:
            previous = db.execute(
                "SELECT * FROM workspace_computer_receipts WHERE workspace_id=? AND request_id=?",
                (workspace_id, command.request_id),
            ).fetchone()
            if previous:
                if previous["fingerprint"] != digest:
                    raise Conflict("Request ID already used with different arguments.")
                return json.loads(previous["response"])
            current = settings_row(db, workspace_id)
            if current["revision"] != command.expected_revision:
                raise Conflict("Computer settings changed. Refresh and try again.")
            _check_provider(db, cloud, workspace_id, command)
            if blocking(db, workspace_id):
                raise Conflict(
                    "Close every open computer in this workspace before changing computer mode.",
                    code="computers_active",
                )
            saved = {
                "mode": command.mode,
                "provider": command.provider if command.mode == "shared" else "docker",
                "profile_id": command.profile_id
                if command.mode == "shared" and command.provider != "docker"
                else None,
                "ownership": command.ownership,
                "revision": current["revision"] + 1,
            }
            db.execute(
                "INSERT INTO workspace_computer_settings("
                "workspace_id,mode,provider,profile_id,ownership,revision,updated_by,updated_at"
                ") VALUES (?,?,?,?,?,?,?,?) "
                "ON CONFLICT(workspace_id) DO UPDATE SET mode=excluded.mode,provider=excluded.provider,"
                "profile_id=excluded.profile_id,ownership=excluded.ownership,revision=excluded.revision,"
                "updated_by=excluded.updated_by,updated_at=excluded.updated_at",
                (
                    workspace_id,
                    saved["mode"],
                    saved["provider"],
                    saved["profile_id"],
                    saved["ownership"],
                    saved["revision"],
                    user_id,
                    stamp(),
                ),
            )
            response = {**settings_row(db, workspace_id), "role": "owner"}
            db.execute(
                "INSERT INTO workspace_computer_receipts VALUES (?,?,?,?)",
                (workspace_id, command.request_id, digest, json.dumps(response)),
            )
            return response

    return write()


def _check_provider(db, cloud, workspace_id, command: UpdateComputer):
    if command.mode != "shared" or command.provider == "docker":
        return
    if not command.provider.startswith("azure_"):
        raise Conflict("Shared computers support the Docker sandbox or an Azure cloud computer.")
    profile = cloud.profiles.get(command.profile_id) if cloud else None
    if not profile or profile.provider != command.provider or profile.workspace_id != workspace_id:
        raise Conflict("Select an available compute profile for this workspace.")
    del db
