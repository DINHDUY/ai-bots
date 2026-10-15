from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING

from agentbot.interfaces import (
    SandboxManager,
)

from agentbot_control.event_store import identifier, stamp
from agentbot_control.runtime import logger

if TYPE_CHECKING:
    from agentbot_control.runtime import Runtime


async def startup(self: Runtime):
    if self.users:
        self.users += 1
        return
    self.lock.acquire()
    try:
        with self.store.transaction() as db:
            owners = [r[0] for r in db.execute("SELECT id FROM users")]
        for owner in owners:
            for bot in self.catalog.list_bots(owner):
                self.ensure(bot)
                await self.migrate_legacy(bot)
        interrupted = {r["session_id"] for r in self.store.recover()}
        for computer in self.store.computers():
            manager = self.kernel.sandboxes
            self.bind(computer)
            if manager.is_cloud(computer["id"]):
                await manager.reconcile(computer["id"], computer["id"] in interrupted)
                continue
            if computer["status"] == "hibernated" and isinstance(manager, SandboxManager):
                report = await manager.inspect(computer["id"])
                if report["lifecycle"] == "missing":
                    self.store.set_computer(computer["bot_id"], computer["id"], "closed")
                elif report["lifecycle"] == "running":
                    await manager.hibernate(computer["id"])
                continue
            if isinstance(manager, SandboxManager):
                try:
                    state = await manager.reconcile(
                        computer["id"],
                        computer["id"] in interrupted
                        or computer["status"] in ("failed", "closing", "provisioning"),
                    )
                    if state != "running":
                        self.store.set_computer(
                            computer["bot_id"],
                            computer["id"],
                            "closed" if state == "missing" else "failed",
                        )
                except Exception:
                    logger.exception("Sandbox reconciliation failed")
                    self.store.set_computer(computer["bot_id"], computer["id"], "failed")
        self.store.prune(prune_captures=False)
        await asyncio.to_thread(self.store.captures.recover)
        self.lifecycle.recover()
        self.files.blobs.recover()
        self.files.blobs.prune()
        self.store.health.progressed("run_cleanup")
        self.accepting = True
        self.users = 1
        self.cloud.start()
    except BaseException:
        self.accepting = False
        self.users = 0
        self.lock.release()
        raise


def bind(self: Runtime, computer):
    manager = self.kernel.sandboxes
    if isinstance(manager, SandboxManager):
        manager.bind(computer["id"], computer["bot_id"] or "", computer["generation"])
        note = getattr(manager, "note_workspace", None)
        if computer.get("workspace_id") and note:
            note(computer["id"], computer["workspace_id"])
        with self.store.transaction() as db:
            legacy = db.execute(
                "SELECT value FROM runtime_settings WHERE key=?",
                ("legacy:" + computer["id"],),
            ).fetchone()
        if legacy:
            manager.legacy[computer["id"]] = json.loads(legacy[0])


async def migrate_legacy(self: Runtime, bot):
    manager = self.kernel.sandboxes
    if self.store.computer(bot.id) or not isinstance(manager, SandboxManager):
        return
    candidate = await manager.legacy_candidate(bot.id)
    if not candidate:
        return
    sid, now = identifier("computer"), stamp()
    with self.store.transaction() as db:
        db.execute(
            "INSERT INTO computer_sessions (id,bot_id,generation,status,created_at,updated_at) VALUES (?,?,1,'failed',?,?)",
            (sid, bot.id, now, now),
        )
        db.execute(
            "INSERT INTO runtime_settings VALUES (?,?)",
            ("legacy:" + sid, json.dumps(candidate)),
        )
        self.store._event(
            db,
            bot.id,
            "session.failed",
            {
                "status": "failed",
                "reason": "Legacy sandbox retained for recovery; close it before starting with the new sandbox image.",
            },
        )


async def shutdown(self: Runtime):
    self.users -= 1
    if self.users:
        return
    self.accepting = False
    for rid, task in list(self.tasks.items()):
        if not task.done():
            with self.store.transaction() as db:
                run = db.execute("SELECT bot_id FROM runs WHERE id=?", (rid,)).fetchone()
            if run:
                self.store.request_stop(run[0], rid, identifier("shutdown"))
            task.cancel()
    if self.tasks:
        try:
            await asyncio.wait_for(
                asyncio.shield(asyncio.gather(*self.tasks.values(), return_exceptions=True)),
                timeout=120,
            )
        except TimeoutError as exc:
            # Keep the process lock while old workers remain; the OS releases it on exit.
            raise RuntimeError(
                "Shutdown could not confirm sandbox termination; pending runs remain quarantined."
            ) from exc
    await self.cloud.shutdown()
    await self.computers.shutdown()
    self.lock.release()
