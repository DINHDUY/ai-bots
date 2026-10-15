from __future__ import annotations

from dataclasses import asdict
from typing import TYPE_CHECKING

from agentbot_control.common import (
    fingerprint,
    identifier,
    packed,
    sanitized,
    stamp,
)
from agentbot_control.repositories import admission
from agentbot_control.schemas import Conflict

if TYPE_CHECKING:
    from agentbot_control.event_store import EventStore


def ensure_bot(self: EventStore, bot, history):
    with self.transaction() as db:
        wid = self._workspace(db, bot.owner_id)
        db.execute(
            "INSERT OR IGNORE INTO bot_streams(bot_id,workspace_id) VALUES (?,?)",
            (bot.id, wid),
        )
        if not db.execute("SELECT imported FROM bot_streams WHERE bot_id=?", (bot.id,)).fetchone()[
            0
        ]:
            for message in history:
                db.execute(
                    "INSERT INTO messages(id,bot_id,seq,role,content) VALUES (?,?,0,?,?)",
                    (
                        identifier("msg"),
                        bot.id,
                        message["role"],
                        str(message["content"]),
                    ),
                )
            db.execute("UPDATE bot_streams SET imported=1 WHERE bot_id=?", (bot.id,))


def admit(
    self: EventStore,
    bot,
    user_id,
    request_id,
    prompt,
    trigger="user",
    secrets=(),
    attachments=(),
    run_mode="computer",
    channel_delivery_id=None,
    allowed_policy_id="*",
):
    body = dict(operation="start", prompt=prompt)
    if run_mode != "computer" or channel_delivery_id:
        body.update(run_mode=run_mode, channel_delivery_id=channel_delivery_id)
    if attachments:
        body["attachment_ids"] = [a["id"] for a in attachments]
    with self.transaction() as db:
        previous = self._receipt(db, bot.id, request_id, body)
        if previous:
            return previous, False
        if self._active(db, bot.id):
            raise Conflict("A step is already running.", code="bot_busy")
        admission.require_run(db, bot.id, self.admission_limits)
        from agentbot_control.shared_computers.resolution import (
            open_bot_computer,
            open_computer,
            uses_shared,
        )

        shared = uses_shared(db, bot.id) if run_mode == "computer" else None
        if shared:
            computer = open_computer(db, shared["workspace_id"])
        elif run_mode == "communication":
            computer = None
        else:
            computer = open_bot_computer(db, bot.id)
        if run_mode == "communication":
            computer = None
        if computer and computer["status"] in ("failed", "closing"):
            raise Conflict(
                "Sandbox needs closure before another run; termination or recovery is unverified.",
                code="recovery_required",
            )
        now = stamp()
        if shared and run_mode == "computer" and (not computer or computer["status"] != "running"):
            raise Conflict(
                "Create the shared workspace computer before running a bot.",
                code="workspace_computer",
            )
        if not shared and not computer and run_mode == "computer":
            admission.require_computer(db, bot.id, self.admission_limits)
            generation = db.execute(
                "SELECT COALESCE(MAX(generation),0)+1 FROM computer_sessions WHERE bot_id=?",
                (bot.id,),
            ).fetchone()[0]
            sid = identifier("computer")
            db.execute(
                "INSERT INTO computer_sessions (id,bot_id,generation,status,created_at,updated_at) VALUES (?,?,?,?,?,?)",
                (sid, bot.id, generation, "provisioning", now, now),
            )
            computer = db.execute("SELECT * FROM computer_sessions WHERE id=?", (sid,)).fetchone()
        rid = identifier("run")
        config = sanitized(asdict(bot), secrets)
        config["attachments"] = attachments
        config["run_mode"] = run_mode
        config["allowed_policy_id"] = allowed_policy_id
        config["version"] = fingerprint(config)
        db.execute(
            "INSERT INTO runs VALUES (?,?,?,?,?,?,?,?,?,?,NULL)",
            (
                rid,
                bot.id,
                computer["id"] if computer else None,
                user_id,
                "preparing",
                sanitized(prompt, secrets),
                packed(config),
                trigger,
                now,
                now,
            ),
        )
        if self.hooks.admission:
            self.hooks.admission.pin(db, bot, rid)
        if self.hooks.channels:
            if channel_delivery_id:
                self.hooks.channels.admit(db, bot, rid, channel_delivery_id)
            else:
                self.hooks.channels.inherit(db, bot, rid, request_id, trigger)
            if trigger in {"user", "human_resume"}:
                self.hooks.channels.user_admitted(db, bot.id)
        self._message(db, bot.id, "user", sanitized(prompt, secrets), rid)
        self._event(db, bot.id, "run.started", {"status": "preparing", "run_mode": run_mode}, rid)
        response = dict(
            run_id=rid,
            session_id=computer["id"] if computer else None,
            generation=computer["generation"] if computer else None,
            run_mode=run_mode,
            status="preparing",
        )
        self._save_receipt(db, bot.id, request_id, body, response)
        return response, True


def ready(self: EventStore, bot_id, rid):
    with self.transaction() as db:
        run = db.execute("SELECT * FROM runs WHERE id=?", (rid,)).fetchone()
        if run["status"] != "preparing":
            return
        db.execute(
            "UPDATE runs SET status='running', updated_at=? WHERE id=?",
            (stamp(), rid),
        )
        db.execute(
            "UPDATE computer_sessions SET status='running', updated_at=? WHERE id=?",
            (stamp(), run["session_id"]),
        )
        self._event(
            db,
            bot_id,
            "session.bound" if run["session_id"] else "run.ready",
            {
                "status": "running",
                "health": "unknown",
                "run_mode": "computer" if run["session_id"] else "communication",
            },
            rid,
        )
