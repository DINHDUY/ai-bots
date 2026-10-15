from __future__ import annotations

import asyncio
from copy import deepcopy
from datetime import UTC, datetime
from time import perf_counter

from agentbot.events import RealTimeEventStreamer
from agentbot.interfaces import (
    ActionResult,
    CheckedSandbox,
    RevisionSandbox,
    TerminationUnverified,
    utc_now,
)

from agentbot_control.policies import scope_for


class ActionArbiter:
    """Serializes whole actions, including approval and context observation.

    Lifecycle changes fence dispatch synchronously in SQLite. Runtime stop drains
    the guarded sandbox before admitting another run on this instance.
    """

    def __init__(self, approvals, streamer, guard, lock):
        self.approvals, self.streamer, self.guard, self.lock = (
            approvals,
            streamer,
            guard,
            lock,
        )

    async def context(self, operation, arguments):
        sandbox = self.guard.sandbox
        if operation == "bash" and isinstance(sandbox, RevisionSandbox):
            try:
                return {"workspace_revision": await self.guard.workspace_revision()}
            except Exception:
                return {}  # No bounded revision => no persistent shell rule.
        if (
            operation in {"file_write", "file_edit"}
            and arguments.get("command") != "view"
            and isinstance(sandbox, RevisionSandbox)
        ):
            return {"file_revision": await self.guard.file_revision(arguments["path"])}
        if operation == "open_browser" and isinstance(sandbox, CheckedSandbox):
            return {"browser_scoped": True}
        return {}

    async def __call__(
        self,
        engine,
        operation,
        arguments,
        detail,
        execute,
        *,
        requires_approval=True,
        step_id=None,
    ):
        async with self.lock:
            self.guard.last_command = None
            frozen = deepcopy(arguments)
            access = self.streamer.context.tool_access
            binding = access.operation(operation, frozen) if access else None
            context_started = perf_counter()
            context = await self.context(operation, frozen)
            context_ms = (perf_counter() - context_started) * 1000
            streamer = self.streamer
            frame, future = RealTimeEventStreamer.begin_approval(
                streamer, engine, operation, detail
            )
            approval = await self.approvals.store.offload(
                lambda: self.approvals.register(
                    streamer.bot_id,
                    streamer.rid,
                    frame,
                    streamer.approval_timeout,
                    streamer.secrets,
                    tool_binding=binding,
                    arguments=frozen,
                    context=context,
                    step_id=step_id,
                    requires_approval=requires_approval,
                    allowed_policy_id=streamer.context.allowed_policy_id,
                )
            )
            started = utc_now()
            result = None
            rechecked, execution_ms = False, 0.0
            try:
                if approval["status"] == "pending":
                    yield frame
                    remaining = max(
                        0,
                        (
                            datetime.fromisoformat(approval["expires_at"]) - datetime.now(UTC)
                        ).total_seconds(),
                    )
                    try:
                        await asyncio.wait_for(asyncio.shield(future), remaining)
                    except TimeoutError:
                        # The monotonic waiter is authoritative even when the wall
                        # clock has not quite reached the serialized timestamp.
                        await self.approvals.store.offload(
                            lambda: self.approvals.expire(approval["id"], force=True)
                        )
                current = await self.approvals.store.offload(
                    lambda: self.approvals.get(approval["id"])
                )
                if current["status"] != "approved":
                    result = ActionResult(
                        False,
                        "Autopilot disabled before execution. Request fresh approval."
                        if current["status"] == "cancelled"
                        and current["decision_source"] == "autopilot"
                        else f"Action {current['status']}; not executed.",
                        cancelled=True,
                    )
                else:
                    check_started = perf_counter()
                    latest_context, rechecked = await self.dispatch_context(
                        operation, frozen, context, approval
                    )
                    context_ms += (perf_counter() - check_started) * 1000
                    if streamer.context.authorize:
                        streamer.context.authorize()
                    if not await self.approvals.store.offload(
                        lambda: self.approvals.claim(approval["id"], arguments, latest_context)
                    ):
                        result = ActionResult(
                            False,
                            "Authorization or action context changed; not executed.",
                            cancelled=True,
                        )
                    else:
                        # The guard passes revisions to the sandbox's checked mutation APIs.
                        scope = scope_for(operation, frozen, context)
                        self.guard.action_context = {
                            "action_id": approval["action_id"],
                            **context,
                            "origin": scope.get("origin") if scope else None,
                        }
                        started = utc_now()
                        execution_started = perf_counter()
                        try:
                            result = await execute()
                        finally:
                            execution_ms = (perf_counter() - execution_started) * 1000
                result.started_at, result.ended_at = started, utc_now()
                await self.approvals.store.offload(
                    lambda: self.approvals.result(approval, result, streamer.secrets)
                )
                yield result
            except asyncio.CancelledError:
                await self.approvals.store.offload(
                    lambda: self.approvals.expire(approval["id"], force=True)
                )
                try:
                    await self.guard.drain()
                except TerminationUnverified as error:
                    unknown = ActionResult(
                        False, str(error), value={"outcome_unknown": True}, started_at=started
                    )
                    await self.approvals.store.offload(
                        lambda: self.approvals.result(approval, unknown, streamer.secrets)
                    )
                    raise
                command = self.guard.last_command
                result = ActionResult(
                    command.ok if command else False,
                    command.text() if command else "Action cancelled; sandbox operations settled.",
                    command=command,
                    cancelled=command.cancelled if command else True,
                    started_at=started,
                )
                await self.approvals.store.offload(
                    lambda: self.approvals.result(approval, result, streamer.secrets)
                )
                raise
            except Exception as exc:
                result = ActionResult(
                    False,
                    str(exc),
                    started_at=started,
                    value={"outcome_unknown": True}
                    if isinstance(exc, TerminationUnverified)
                    else None,
                )
                await self.approvals.store.offload(
                    lambda: self.approvals.result(approval, result, streamer.secrets)
                )
                raise
            finally:
                self.approvals.store.record_frame(
                    streamer.bot_id,
                    streamer.rid,
                    {
                        "event": "telemetry",
                        "data": {
                            "category": "action.timing",
                            "action_id": approval["action_id"],
                            "context_check_ms": round(context_ms, 3),
                            "context_reads": 1 + int(rechecked),
                            "execution_ms": round(execution_ms, 3),
                        },
                    },
                )
                streamer._pending.pop(approval["id"], None)
                if not future.done():
                    future.cancel()
                self.guard.action_context = {}

    async def dispatch_context(self, operation, arguments, context, approval):
        """Reuse the observation only when the mutation itself enforces its revision.

        The final DB claim still checks revocation, arguments, generation, grants,
        and human control. Pending/manual/rule approvals retain the second read.
        """
        method, revision = {
            "bash": ("run_command_checked", "workspace_revision"),
            "file_write": ("write_workspace_file_checked", "file_revision"),
            "file_edit": ("write_workspace_file_checked", "file_revision"),
        }.get(operation, (None, None))
        eligible = (
            approval["status"] == "approved"
            and approval.get("decision_source") == "autopilot"
            and bool(context.get(revision))
            and callable(getattr(self.guard.sandbox, method or "", None))
            and arguments.get("command") != "view"
        )
        if eligible:
            return context, False
        return await self.context(operation, arguments), True
