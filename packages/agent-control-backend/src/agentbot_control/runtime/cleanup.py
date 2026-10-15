from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from agentbot_control.event_store import identifier, stamp
from agentbot_control.runtime import logger
from agentbot_control.schemas import Conflict

if TYPE_CHECKING:
    from agentbot_control.runtime import Runtime


def stop(self: Runtime, bot_id, rid, request_id, *, cancel_channel=True):
    if cancel_channel:
        self.channels.stop_bot(bot_id, rid)
    result = self.store.request_stop(bot_id, rid, request_id)
    task = self.tasks.get(rid)
    if task and not task.done() and not task.cancelling():
        task.cancel()
    return result


async def close(self: Runtime, bot_id, request_id, expected=None, idle_before=None, *, actor=None):
    from agentbot_control.shared_computers.resolution import bot_blocked

    if bot_blocked(self.store, bot_id):
        raise Conflict(
            "This workspace uses one shared computer. Manage it from workspace settings.",
            code="workspace_computer",
        )
    if self.cloud.selected(bot_id):
        return await self.cloud.retire(
            bot_id, request_id, expected, idle=bool(idle_before), actor=actor
        )
    async with self.mutex(bot_id):
        body = dict(operation="close", session_id=expected)
        previous = self.store.receipt(bot_id, request_id, body)
        if previous and previous["status"] == "closed":
            return previous
        computer = self.store.computer(bot_id)
        if idle_before and computer:
            retention = self.lifecycle.retention(computer["id"])
            if (
                self.store.active(bot_id)
                or self.control.state(bot_id)["lease"]
                or computer["updated_at"] > idle_before
                or (retention.get("keep_warm_until") or "") > stamp()
            ):
                return {"status": "retained", "session_id": computer["id"]}
        if previous and computer and computer["id"] != previous["session_id"]:
            # A replayed close can never close a replacement instance.
            return {"status": "closed", "session_id": previous["session_id"]}
        if expected and (not computer or computer["id"] != expected):
            raise Conflict("The sandbox instance changed.")
        lease = self.control.state(bot_id)["lease"]
        if lease:
            try:
                await self.control.release_by_id(lease["id"])
            except Exception:
                logger.warning(
                    "Input service unavailable during close; container removal will fence remaining processes"
                )
        if not previous:
            with self.store.transaction() as db:
                if computer and computer["status"] != "closed":
                    db.execute(
                        "UPDATE computer_sessions SET status='closing',updated_at=? WHERE id=?",
                        (stamp(), computer["id"]),
                    )
                    self.store._event(db, bot_id, "session.closing", {"status": "closing"})
                self.store._save_receipt(
                    db,
                    bot_id,
                    request_id,
                    body,
                    {
                        "status": "closing",
                        "session_id": computer["id"] if computer else None,
                    },
                )
        run = self.store.active(bot_id)
        if run:
            self.stop(bot_id, run["id"], identifier("close_stop"))
        if computer and computer["status"] != "closed":
            try:
                # Force-removal terminates container processes before publishing closed.
                creation = self.creations.get(run["id"]) if run else None
                if creation:
                    await asyncio.gather(asyncio.shield(creation), return_exceptions=True)
                await self.kernel.close_session(computer["id"])
                task = self.tasks.get(run["id"]) if run else None
                if task:
                    await asyncio.wait_for(asyncio.shield(task), timeout=120)
                if run:
                    self.store.finish(bot_id, run["id"], "cancelled", "Sandbox closed.")
                self.store.set_computer(bot_id, computer["id"], "closed")
                lease = self.control.state(bot_id)["lease"]
                if lease:
                    await self.control.release_by_id(lease["id"])
            except Exception:
                self.store.set_computer(bot_id, computer["id"], "failed")
                raise Conflict("Sandbox closure could not be confirmed.")
        result = dict(status="closed", session_id=computer["id"] if computer else None)
        with self.store.transaction() as db:
            db.execute(
                "UPDATE command_receipts SET response=? WHERE bot_id=? AND request_id=?",
                (json.dumps(result), bot_id, request_id),
            )
        return result


async def sweep(self: Runtime, idle_seconds):
    while True:
        await asyncio.sleep(min(10, max(0.1, idle_seconds)))
        for computer in self.store.computers():
            if not computer.get("bot_id"):
                await _sweep_shared(self, computer, idle_seconds)
                continue
            retention = self.lifecycle.retention(computer["id"])
            if retention.get("keep_warm_until", "") and retention["keep_warm_until"] > stamp():
                continue
            idle = (
                datetime.now(UTC) - datetime.fromisoformat(computer["updated_at"])
            ).total_seconds()
            if (
                (
                    computer["status"] == "running"
                    or (
                        computer["status"] == "hibernated"
                        and retention.get("retain_until", "9999") <= stamp()
                    )
                )
                and not self.store.active(computer["bot_id"])
                and not self.control.state(computer["bot_id"])["lease"]
                and idle >= idle_seconds
            ):
                try:
                    await self.close(
                        computer["bot_id"],
                        identifier("idle"),
                        computer["id"],
                        idle_before=(
                            datetime.now(UTC) - timedelta(seconds=idle_seconds)
                        ).isoformat(),
                    )
                except Exception:
                    logger.exception("Idle close failed")
            elif (
                computer["status"] == "running"
                and idle >= max(0, idle_seconds - 60)
                and not retention.get("warned")
            ):
                with self.store.transaction() as db:
                    db.execute(
                        "INSERT INTO computer_retention(session_id,warned) VALUES (?,1) ON CONFLICT(session_id) DO UPDATE SET warned=1",
                        (computer["id"],),
                    )
                    self.store._event(
                        db,
                        computer["bot_id"],
                        "lifecycle.idle_warning",
                        {"seconds_remaining": max(0, idle_seconds - idle)},
                    )
        self.store.prune(prune_captures=False)
        self.files.blobs.prune()
        self.store.health.progressed("run_cleanup")


async def _sweep_shared(self: Runtime, computer, idle_seconds):
    from agentbot_control.shared_computers.resolution import session_busy_store

    retention = self.lifecycle.retention(computer["id"])
    if retention.get("keep_warm_until", "") and retention["keep_warm_until"] > stamp():
        return
    idle = (datetime.now(UTC) - datetime.fromisoformat(computer["updated_at"])).total_seconds()
    due = (
        computer["status"] == "running"
        or (computer["status"] == "hibernated" and retention.get("retain_until", "9999") <= stamp())
    ) and idle >= idle_seconds
    if due and not session_busy_store(self.store, computer["id"]):
        try:
            await self.shared_computers.close_idle(computer)
        except Exception:
            logger.exception("Idle close failed")
        return
    if (
        computer["status"] == "running"
        and idle >= max(0, idle_seconds - 60)
        and not retention.get("warned")
    ):
        from agentbot_control.shared_computers.resolution import warn_idle

        await self.store.offload(
            lambda: warn_idle(self.store, computer, max(0, idle_seconds - idle))
        )
