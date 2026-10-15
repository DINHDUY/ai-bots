from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from agentbot_tools.registry import REGISTRY
from fastapi import HTTPException

from agentbot_control.channels import LIBRARY, TOOL, Participation, bounded
from agentbot_control.event_store import (
    identifier,
    packed,
    stamp,
)
from agentbot_control.schemas import Conflict

if TYPE_CHECKING:
    from agentbot_control.channels import Channels


def sync_bot(self: Channels, db, bot):
    stream = db.execute("SELECT workspace_id FROM bot_streams WHERE bot_id=?", (bot.id,)).fetchone()
    if not stream:
        return
    wid = stream[0]
    self._channel(db, wid)
    capabilities = packed(
        sorted(
            {
                REGISTRY[f"{b['library_id']}/{b['tool_id']}"].library_name
                for b in self.tools.rows(db, bot.id)
                if f"{b['library_id']}/{b['tool_id']}" in REGISTRY and b["library_id"] != LIBRARY
            }
        )
    )
    row = db.execute("SELECT * FROM workspace_bot_directory WHERE bot_id=?", (bot.id,)).fetchone()
    if not row:
        db.execute(
            "INSERT INTO workspace_bot_directory(bot_id,workspace_id,owner_id,name,capabilities,enrollment_id,updated_at) VALUES (?,?,?,?,?,?,?)",
            (
                bot.id,
                wid,
                bot.owner_id,
                bot.name,
                capabilities,
                identifier("enrollment"),
                stamp(),
            ),
        )
    elif row["name"] != bot.name or row["capabilities"] != capabilities:
        db.execute(
            "UPDATE workspace_bot_directory SET name=?,capabilities=?,revision=revision+1,updated_at=? WHERE bot_id=?",
            (bot.name, capabilities, stamp(), bot.id),
        )
        if row["published"]:
            self.event(db, wid, "bot.profile_updated", {"bot_id": bot.id}, directory=True)
    self.binding_changed(db, bot.id)


def binding_changed(self: Channels, db, bid):
    row = db.execute("SELECT * FROM workspace_bot_directory WHERE bot_id=?", (bid,)).fetchone()
    if row and row["state"] == "enabled" and not self._has_bundle(db, bid):
        self._retire(db, row, "disabled", "bot.collaboration_disabled")


def _retire(self: Channels, db, row, state, kind):
    for thread in db.execute(
        "SELECT id FROM channel_threads WHERE origin_bot_id=? AND state IN ('open','waiting_peer')",
        (row["bot_id"],),
    ).fetchall():
        self._cancel(db, thread[0])
    db.execute(
        "UPDATE workspace_bot_directory SET state=?,revision=revision+1,updated_at=? WHERE bot_id=?",
        (state, stamp(), row["bot_id"]),
    )
    db.execute(
        "UPDATE channel_deliveries SET state='cancelled',reason=? WHERE (target_bot_id=? OR source_bot_id=?) AND state IN ('queued','blocked')",
        ("participation_" + state, row["bot_id"], row["bot_id"]),
    )
    db.execute(
        "UPDATE channel_continuations SET state='cancelled' WHERE bot_id=? AND state IN ('waiting','queued')",
        (row["bot_id"],),
    )
    if row["published"]:
        self.event(
            db,
            row["workspace_id"],
            kind,
            {"bot_id": row["bot_id"], "name": row["name"], "state": state},
            directory=True,
        )


def retire(self: Channels, db, bid, *, final=False):
    row = db.execute("SELECT * FROM workspace_bot_directory WHERE bot_id=?", (bid,)).fetchone()
    state = "removed" if final else "leaving"
    if row and row["state"] != state:
        self._retire(db, row, state, "bot.left" if final else "bot.leaving")


def expire(self: Channels, db):
    for row in db.execute(
        "SELECT * FROM workspace_bot_directory WHERE state='enabled' AND expires_at IS NOT NULL AND expires_at<=?",
        (stamp(),),
    ).fetchall():
        self._retire(db, row, "expired", "bot.participation_expired")


def enroll(self: Channels, db, bid, uid, command):
    self.available()
    bot = self.catalog.get_bot_by_id_tx(db, bid)
    if not bot or bot.owner_id != uid:
        raise HTTPException(403, "Only the bot owner can publish and enroll this bot.")
    self.sync_bot(db, bot)
    row = db.execute("SELECT * FROM workspace_bot_directory WHERE bot_id=?", (bid,)).fetchone()
    if (
        row["state"] == "leaving"
        and db.execute(
            "SELECT 1 FROM computer_sessions WHERE status IN ('closing','failed') AND ("
            "bot_id=? OR (bot_id IS NULL AND workspace_id=(SELECT workspace_id FROM bot_streams WHERE bot_id=?)))",
            (bid, bid),
        ).fetchone()
    ):
        raise Conflict("Finish computer retirement before restoring collaboration.")
    self._role(db, uid, row["workspace_id"])
    if row["revision"] != command.revision:
        raise Conflict("Collaboration settings changed. Reload and review your draft.")
    expiry = command.expires_at
    if expiry and (not expiry.tzinfo or expiry <= datetime.now(UTC)):
        raise Conflict("Expiry must be a future time with a timezone.")
    selection = [
        self.tools.selection(b) for b in self.tools.rows(db, bid) if b["library_id"] != LIBRARY
    ]
    if command.enabled:
        selection.append(self.tools.item(LIBRARY, TOOL))
    self.tools.replace(db, bid, selection, uid, provenance="collaboration")
    generation = (
        row["enrollment_id"]
        if row["state"] == "enabled" and command.enabled
        else identifier("enrollment")
    )
    db.execute(
        "UPDATE workspace_bot_directory SET state=?,published=1,purpose=?,expires_at=?,enrollment_id=?,revision=revision+1,updated_at=? WHERE bot_id=?",
        (
            "enabled" if command.enabled else "disabled",
            bounded(command.purpose, 1600) if command.purpose else "",
            expiry.astimezone(UTC).isoformat() if expiry else None,
            generation,
            stamp(),
            bid,
        ),
    )
    self.event(
        db,
        row["workspace_id"],
        "bot.joined" if command.enabled else "bot.collaboration_disabled",
        {
            "bot_id": bid,
            "name": bot.name,
            "state": "enabled" if command.enabled else "disabled",
        },
        directory=True,
    )


def creation(self: Channels, db, bot, join=None):
    self.sync_bot(db, bot)
    if join is True:
        self.enroll(db, bot.id, bot.owner_id, Participation(revision=0, enabled=True))


def configure(self: Channels, uid, wid, command):
    with self.store.transaction() as db:
        configure_tx(self, db, uid, wid, command)
    return self.snapshot(uid, wid)


def configure_tx(self: Channels, db, uid, wid, command):
    self.available()
    self._role(db, uid, wid, owner=True)
    row = self._channel(db, wid)
    if row["revision"] != command.revision:
        raise Conflict("Channel settings changed. Reload and review your draft.")
    for bid in set(command.enroll_bot_ids):
        bot = self.catalog.get_bot_by_id_tx(db, bid)
        if not bot:
            raise Conflict("recipient_removed")
        self.sync_bot(db, bot)
        entry = db.execute(
            "SELECT * FROM workspace_bot_directory WHERE bot_id=? AND workspace_id=?",
            (bid, wid),
        ).fetchone()
        if not entry:
            raise Conflict("Bots must belong to this workspace.")
        self.enroll(
            db,
            bid,
            uid,
            Participation(
                revision=entry["revision"],
                enabled=True,
                purpose=entry["purpose"],
            ),
        )
    db.execute(
        "UPDATE workspace_channels SET enabled=?,revision=revision+1 WHERE workspace_id=?",
        (command.enabled, wid),
    )
    db.execute(
        "INSERT INTO channel_enrollment_policies VALUES (?,?,?) ON CONFLICT(workspace_id,owner_id) DO UPDATE SET enabled=excluded.enabled",
        (wid, uid, command.enroll_future),
    )
    if not command.enabled:
        for thread in db.execute(
            "SELECT id FROM channel_threads WHERE workspace_id=? AND state IN ('open','waiting_peer')",
            (wid,),
        ).fetchall():
            self._cancel(db, thread[0], "cancelled")
    self.event(db, wid, "channel.configured", {"enabled": command.enabled})


def participation(self: Channels, uid, bid):
    bot = self.workspaces.bot(uid, bid, "owner")
    self.ensure(bot)
    with self.store.transaction() as db:
        self.expire(db)
        return dict(
            db.execute("SELECT * FROM workspace_bot_directory WHERE bot_id=?", (bid,)).fetchone()
        )
