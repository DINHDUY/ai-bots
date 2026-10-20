from __future__ import annotations

import asyncio
import base64
import json
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from agentbot_control.control import digest
from agentbot_control.event_store import identifier, stamp
from agentbot_control.schemas import Conflict

if TYPE_CHECKING:
    from agentbot_control.control import Control


async def acquire(self: Control, bot_id, sid, user, token, command):
    if self.windows.config(bot_id) or (self.macos and self.macos.config(bot_id)):
        raise Conflict(
            "Use Take control on this PC; remote browser input is unavailable for Windows."
        )
    async with self.mutex(bot_id):
        receipt_body = {
            "operation": "control.acquire",
            "session_id": sid,
            "principal": user.id,
            "login": digest(token),
            **command.model_dump(),
        }
        previous = self.store.receipt(bot_id, command.request_id, receipt_body)
        if previous:
            self.check(
                bot_id,
                sid,
                user,
                token,
                previous["lease_id"],
                command.client_id,
                previous["fence"],
            )
            return self.state(bot_id)["lease"]
        computer, sandbox = await self.computer_existing(bot_id, sid)
        if computer["generation"] != command.generation:
            raise Conflict("Computer generation changed.")
        active = self.state(bot_id)["lease"]
        if active:
            if active["expires_at"] <= stamp():
                await self.release_by_id(active["id"])
            elif (
                active["client_id"] == command.client_id
                and active["user_id"] == user.id
                and active["surface"] == command.surface
            ):
                self.check(
                    bot_id,
                    sid,
                    user,
                    token,
                    active["id"],
                    command.client_id,
                    active["fence"],
                )
                with self.store.transaction() as db:
                    self.store._save_receipt(
                        db,
                        bot_id,
                        command.request_id,
                        receipt_body,
                        {"lease_id": active["id"], "fence": active["fence"]},
                    )
                return active
            else:
                raise Conflict("Another tab owns control.")
        with self.store.transaction() as db:
            db.execute(
                "INSERT INTO computer_control(session_id,paused) VALUES (?,1) ON CONFLICT(session_id) DO UPDATE SET paused=1",
                (sid,),
            )
            from agentbot_control.shared_computers.resolution import emit

            emit(
                self.store,
                db,
                bot_id,
                "control.waiting_for_safe_point",
                {"paused": True, "actor": user.id},
                sid,
            )
        from agentbot_control.shared_computers.resolution import still_active, takeover_runs

        for run in takeover_runs(self.store, bot_id, sid):
            self.stop(run["bot_id"], run["id"], identifier("takeover"))
            task = self.tasks.get(run["id"])
            if task:
                try:
                    await asyncio.wait_for(asyncio.shield(task), 30)
                except TimeoutError:
                    raise Conflict(
                        "Waiting for sandbox operations to stop. Try acquiring control again."
                    )
                except asyncio.CancelledError:
                    if not task.done():
                        raise
        if still_active(self.store, bot_id, sid):
            raise Conflict("Sandbox termination is not yet verified.")
        lock = self.action_locks.setdefault(sid, asyncio.Lock())
        async with lock:
            await self.computer_existing(bot_id, sid)
            image = await sandbox.capture(command.surface)
            self.store.record_capture(
                bot_id, None, base64.b64encode(image).decode(), image.metadata
            )
            with self.store.transaction() as db:
                db.execute(
                    "UPDATE computer_control SET fence=fence+1 WHERE session_id=?",
                    (sid,),
                )
                fence = db.execute(
                    "SELECT fence FROM computer_control WHERE session_id=?", (sid,)
                ).fetchone()[0]
                lease_id = identifier("lease")
                expiry = (datetime.now(UTC) + timedelta(seconds=30)).isoformat()
                db.execute(
                    "INSERT INTO control_leases(id,bot_id,session_id,generation,user_id,login_digest,client_id,surface,surface_id,viewport_revision,fence,expires_at,status) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,'active')",
                    (
                        lease_id,
                        bot_id,
                        sid,
                        computer["generation"],
                        user.id,
                        digest(token),
                        command.client_id,
                        command.surface,
                        image.metadata["surface_id"],
                        image.metadata["viewport_revision"],
                        fence,
                        expiry,
                    ),
                )
                from agentbot_control.shared_computers.resolution import emit

                emit(
                    self.store,
                    db,
                    bot_id,
                    "control.acquired",
                    {
                        "actor": user.id,
                        "client_id": command.client_id,
                        "surface": command.surface,
                        "fence": fence,
                        "paused": True,
                    },
                    sid,
                )
                self.store._save_receipt(
                    db,
                    bot_id,
                    command.request_id,
                    receipt_body,
                    {"lease_id": lease_id, "fence": fence},
                )
            self.tokens[lease_id] = token
            return self.state(bot_id)["lease"]


def renew(self: Control, bot_id, sid, user, token, command):
    self.check(bot_id, sid, user, token, command.lease_id, command.client_id, command.fence)
    with self.store.transaction() as db:
        expiry = (datetime.now(UTC) + timedelta(seconds=30)).isoformat()
        db.execute(
            "UPDATE control_leases SET expires_at=? WHERE id=?",
            (expiry, command.lease_id),
        )
    return {"expires_at": expiry}


async def release_by_id(self: Control, lease_id):
    async with self.locks.setdefault(lease_id, asyncio.Lock()):
        with self.store.transaction() as db:
            row = db.execute(
                "SELECT * FROM control_leases WHERE id=? AND status IN ('active','releasing')",
                (lease_id,),
            ).fetchone()
            if not row:
                return
            db.execute(
                "UPDATE control_leases SET status='releasing' WHERE id=?",
                (lease_id,),
            )
        await self.close_lease(lease_id)
        async with self.action_locks.setdefault(row["session_id"], asyncio.Lock()):
            computer = self.store.computer(row["bot_id"])
            if computer and computer["id"] == row["session_id"] and computer["status"] != "closed":
                self.bind(computer)
                report = await self.kernel.sandboxes.inspect(row["session_id"])
                if report["lifecycle"] == "running":
                    sandbox = await self.kernel.sandboxes.existing(row["session_id"])
                    image = await sandbox.human_input(
                        row["surface"],
                        {"kind": "release", **json.loads(row["held"])},
                    )
                    recording = self.toolkit.recording(lease_id)
                    if not recording or not recording["private"]:
                        self.store.record_capture(
                            row["bot_id"],
                            None,
                            base64.b64encode(image).decode(),
                            image.metadata,
                        )
                elif report["lifecycle"] not in {
                    "exited",
                    "missing",
                    "stopped",
                    "dead",
                }:
                    raise Conflict("Cannot confirm input service has stopped.")
            with self.store.transaction() as db:
                db.execute(
                    "UPDATE control_leases SET status='released' WHERE id=?",
                    (lease_id,),
                )
                from agentbot_control.shared_computers.resolution import emit

                emit(
                    self.store,
                    db,
                    row["bot_id"],
                    "control.released",
                    {"paused": True, "actor": row["user_id"]},
                    row["session_id"],
                )
        self.tokens.pop(lease_id, None)
        with self.store.transaction() as db:
            db.execute(
                "UPDATE recordings SET state='stopped' WHERE lease_id=?",
                (lease_id,),
            )


def retire(self: Control, bot_id, sid):
    """Called only after Docker has confirmed all instance processes stopped."""
    with self.store.transaction() as db:
        rows = db.execute(
            "SELECT id,user_id FROM control_leases WHERE session_id=? AND status IN ('active','releasing')",
            (sid,),
        ).fetchall()
        for row in rows:
            db.execute(
                "UPDATE control_leases SET status='released' WHERE id=?",
                (row["id"],),
            )
            db.execute(
                "UPDATE terminals SET status='closed' WHERE lease_id=?",
                (row["id"],),
            )
            db.execute(
                "UPDATE recordings SET state='stopped' WHERE lease_id=?",
                (row["id"],),
            )
            from agentbot_control.shared_computers.resolution import emit

            emit(
                self.store,
                db,
                bot_id,
                "control.released",
                {
                    "paused": True,
                    "actor": row["user_id"],
                    "reason": "instance_stopped",
                },
                sid,
            )
            self.tokens.pop(row["id"], None)
