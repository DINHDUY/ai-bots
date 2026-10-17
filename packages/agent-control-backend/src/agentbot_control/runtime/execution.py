from __future__ import annotations

import asyncio
import json
from time import perf_counter
from typing import TYPE_CHECKING

from agentbot.execution import CommunicationSandbox
from agentbot.execution import RunYield as PeerWait
from agentbot.interfaces import (
    ProtocolSandbox,
    SandboxError,
)

from agentbot_control.approvals import ActionArbiter
from agentbot_control.dispatch import GuardedSandbox
from agentbot_control.event_store import identifier, protected, sanitized
from agentbot_control.run_streamer import RunStreamer
from agentbot_control.runtime import logger
from agentbot_control.schemas import Conflict

if TYPE_CHECKING:
    from agentbot_control.runtime import Runtime


async def start(
    self: Runtime,
    user,
    bot,
    request_id,
    prompt,
    trigger="user",
    attachment_ids=(),
    program=None,
    resume_sid=None,
    allowed_policy_id="*",
    run_mode="computer",
    channel_delivery_id=None,
):
    if not self.store.health.admitting():
        raise Conflict("A required worker is unavailable", code="worker_unavailable")
    if not self.accepting:
        raise Conflict("Control runtime is shutting down.")
    async with self.mutex(bot.id):
        self.ensure(bot)
        self.workspaces.bot(user.id, bot.id, "write")
        request_body = dict(operation="start", prompt=prompt)
        if run_mode not in {"computer", "communication"}:
            raise Conflict("Invalid run mode.")
        if run_mode != "computer" or channel_delivery_id:
            request_body.update(run_mode=run_mode, channel_delivery_id=channel_delivery_id)
        if attachment_ids:
            request_body["attachment_ids"] = list(attachment_ids)
        previous = self.store.receipt(bot.id, request_id, request_body)
        if previous:
            return previous
        if run_mode == "computer":
            self.windows.require_run(bot, user.id)
            await self.macos.require_run(bot, user.id)
            self.cloud.require_run(bot, user.id)
            from agentbot_control.shared_computers.resolution import ensure_runnable

            ensure_runnable(self.store, self.cloud, bot)
            if channel_delivery_id:
                computer = self.store.computer(bot.id)
                if not computer or computer["status"] != "running":
                    raise Conflict("waiting_for_computer", code="computer_unavailable")
        if self.control.state(bot.id)["lease"]:
            raise Conflict(
                "Human control must be released before running the agent.", code="human_control"
            )
        if resume_sid:
            computer = self.store.computer(bot.id)
            if not computer or computer["id"] != resume_sid or computer["status"] != "running":
                raise Conflict("Computer changed before resume.")
            with self.store.transaction() as db:
                db.execute(
                    "UPDATE computer_control SET paused=0 WHERE session_id=?",
                    (resume_sid,),
                )
                self.store._event(
                    db,
                    bot.id,
                    "control.resumed",
                    {"paused": False, "actor": user.id},
                )
        if self.control.paused(bot.id):
            raise Conflict(
                "Agent is paused. Release human control and explicitly resume it.",
                code="human_control",
            )
        attachments = await self.files.attachments(bot.id, user.id, attachment_ids)
        model = self.catalog.open_model_config(bot.owner_id, bot)
        if model is None:
            raise Conflict(
                "This bot has no API key. Choose a credential in settings.",
                code="credential_required",
            )
        # Bound, sanitized durable context; provider secrets are never persisted in run configuration.
        context = [
            {"role": m["role"], "content": m["content"]}
            for m in self.store.messages(bot.id)["messages"]
        ]

        def admit():
            return self.store.admit(
                bot,
                user.id,
                request_id,
                prompt,
                trigger,
                (model.api_key,),
                attachments,
                run_mode=run_mode,
                channel_delivery_id=channel_delivery_id,
                allowed_policy_id=allowed_policy_id,
            )

        cancelled = False
        admission_task = asyncio.create_task(self.store.offload(admit))
        while True:
            try:
                response, created = await asyncio.shield(admission_task)
                break
            except asyncio.CancelledError:
                cancelled = True
                if admission_task.cancelled():
                    raise
        if created:
            if attachments:
                context.append(
                    {
                        "role": "user",
                        "content": "Explicit attachments available in this workspace: "
                        + json.dumps(attachments),
                    }
                )
            rid = response["run_id"]
            streamer = RunStreamer(
                self.store, self.approvals, bot.id, rid, self.approval_timeout, (model.api_key,)
            )
            streamer.context.request_intent = trigger
            streamer.context.run_mode = run_mode
            self.streamers[rid] = streamer
            streamer.context.allowed_policy_id = allowed_policy_id
            streamer.context.authorize = lambda: self.workspaces.bot(user.id, bot.id, "write")
            task = asyncio.create_task(
                self._execute(bot, response, prompt, context, model, streamer, program)
            )
            self.tasks[rid] = task

            def settled(finished):
                self.tasks.pop(rid, None)
                if finished.cancelled() and rid not in self.started:
                    self.store.finish(bot.id, rid, "cancelled", "Stopped before execution.")
                    self.streamers.pop(rid, None)
                self.started.discard(rid)

            task.add_done_callback(settled)
        if cancelled:
            raise asyncio.CancelledError()
        return response


async def _execute(self: Runtime, bot, response, prompt, context, model, streamer, program=None):
    rid, sid = response["run_id"], response["session_id"]
    self.started.add(rid)
    guard = None
    creation = None
    status, outcome = "completed", None
    artifacts = set()
    persistence_ms, persisted_frames = 0.0, 0
    try:
        from agentbot_control.repositories.macos_tasks import deadline

        task_budget = await self.store.database.read(lambda db: deadline(db, rid))
        async with asyncio.timeout(min(self.run_timeout, task_budget or self.run_timeout)):
            if sid:
                self.bind(self.store.computer(bot.id))
                creation = asyncio.create_task(self.kernel.sandboxes.get_or_create(sid))
                self.creations[rid] = creation
                sandbox = await asyncio.shield(creation)
                guard = GuardedSandbox(sandbox)
                self.guards[rid] = guard
            else:
                sandbox = CommunicationSandbox()
            if isinstance(sandbox, ProtocolSandbox) and await guard.approval_protocol() != 2:
                raise SandboxError(
                    "This computer uses an older sandbox image. Rebuild agentbot-sandbox, then close and recreate this computer for B2 execution."
                )
            streamer.context.tool_access = self.tools.access(bot.id, rid, sandbox)
            streamer.context.sandbox_guard = guard
            if self.workspace_features and sid:
                self.toolkit.bind_tools(bot.id, streamer, context)
            self.channels.bind(bot.id, rid, streamer, context)
            self.store.ready(bot.id, rid)
            streamer.action_handler = (
                ActionArbiter(
                    self.approvals,
                    streamer,
                    guard,
                    self.action_locks.setdefault(sid, asyncio.Lock()),
                )
                if sid
                else None
            )
            frames = (
                program(guard, streamer)
                if program
                else self._communication(bot, prompt, context, model, streamer, sandbox)
                if not sid
                else self.kernel.process_agent_request(
                    bot.framework,
                    prompt,
                    sid,
                    streamer,
                    bot.instructions,
                    model,
                    conversation_id=bot.id,
                    memory_context=context,
                    sandbox=guard,
                    persist_history=False,
                )
            )
            async for frame in frames:
                if frame.get("event") == "artifact_written" and len(artifacts) < 20:
                    artifacts.add(frame.get("meta", {}).get("path", ""))
                if frame.get("event") == "approval_required":
                    continue  # Stored when the waiter was registered, before it can be decided.
                persistence_started = perf_counter()
                if frame.get("type") == "SCREENSHOT_CAPTURE":
                    await self.store.offload(
                        lambda: self.store.record_capture(
                            bot.id, rid, frame.get("payload", ""), frame.get("capture")
                        )
                    )
                else:
                    await self.store.offload(
                        lambda: self.store.record_frame(bot.id, rid, frame, (model.api_key,))
                    )
                persistence_ms += (perf_counter() - persistence_started) * 1000
                persisted_frames += 1
                if frame.get("type") == "ERROR":
                    status, outcome = "failed", "The agent reported an error."
    except PeerWait:
        outcome = "Waiting for a peer reply."
    except asyncio.CancelledError:
        status, outcome = "cancelled", "Stopped after sandbox operations settled."
    except TimeoutError:
        status, outcome = "failed", "Run deadline exceeded."
    except Exception as exc:
        logger.exception("Run failed: %s", rid)
        status, outcome = "failed", sanitized(str(exc), (model.api_key,))
    finally:
        self.store.record_frame(
            bot.id,
            rid,
            {
                "event": "telemetry",
                "data": {
                    "category": "event.persistence",
                    "duration_ms": round(persistence_ms, 3),
                    "frames": persisted_frames,
                },
            },
        )

        async def finalize():
            nonlocal guard, outcome
            try:
                if (
                    creation
                    and creation.done()
                    and not creation.cancelled()
                    and creation.exception()
                ):
                    self.store.set_computer(bot.id, sid, "failed")
                    self.store.finish(bot.id, rid, "failed", outcome)
                    return
                if creation and guard is None:
                    sandbox = await asyncio.shield(creation)
                    guard = GuardedSandbox(sandbox)
                if guard:
                    await guard.drain()
                if (
                    status == "completed"
                    and guard
                    and callable(getattr(guard.sandbox, "files", None))
                ):
                    for path in artifacts:
                        if path and not protected(path):
                            try:
                                revision = await guard.sandbox.file_revision(path)
                                await self.files.snapshot(bot.id, sid, path, revision, rid)
                            except Exception:
                                with self.store.transaction() as db:
                                    self.store._event(
                                        db,
                                        bot.id,
                                        "artifact.unavailable",
                                        {
                                            "path": path,
                                            "reason": "Output changed or exceeded retention limits.",
                                        },
                                        rid,
                                    )
                if status == "completed" and streamer.context.channel_waiting:
                    outcome = streamer.context.channel_wait_reason or "Waiting for a peer reply."
                self.store.finish(bot.id, rid, status, outcome)
            except Exception as exc:
                logger.exception("Termination is unverified for run %s", rid)
                self.store.request_stop(bot.id, rid, identifier("unverified"))
                self.store.set_computer(bot.id, sid, "failed")
                if guard and getattr(guard.sandbox, "provider", None) in {
                    "windows_local",
                    "macos_local",
                }:
                    self.store.finish(
                        bot.id, rid, "interrupted", sanitized(str(exc), (model.api_key,))
                    )
            finally:
                self.streamers.pop(rid, None)
                self.guards.pop(rid, None)
                self.creations.pop(rid, None)

        # Stop can arrive after execution has ended, while native cancellation or
        # artifact retention is still pending. Keep this task owned and await it
        # through cancellation so neither cleanup nor the final event is lost.
        finalizer = asyncio.create_task(finalize())
        while True:
            try:
                await asyncio.shield(finalizer)
                break
            except asyncio.CancelledError:
                if finalizer.cancelled():
                    raise
                if status == "completed":
                    status, outcome = "cancelled", "Stopped after sandbox operations settled."
