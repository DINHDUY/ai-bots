"""The control process owns execution; sockets are only observers/command clients."""

from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agentbot_control.approvals import Approvals
    from agentbot_control.autopilot import Autopilot
    from agentbot_control.channels import Channels
    from agentbot_control.cloud import CloudComputers
    from agentbot_control.composition import Services
    from agentbot_control.computer import Computers
    from agentbot_control.control import Control
    from agentbot_control.event_store import EventStore
    from agentbot_control.files import Files
    from agentbot_control.groups import Groups
    from agentbot_control.lifecycle import Lifecycle
    from agentbot_control.policies import Policies
    from agentbot_control.routines import Routines
    from agentbot_control.terminals import Terminals
    from agentbot_control.tool_libraries import ToolLibraries
    from agentbot_control.toolkit import Toolkit
    from agentbot_control.windows import WindowsComputers
    from agentbot_control.workflow_imports.service import WorkflowImports
    from agentbot_control.workspace_deletions.service import WorkspaceDeletions
    from agentbot_control.workspaces import Workspaces

from time import perf_counter

from agentbot.execution import CommunicationSandbox
from agentbot.execution import RunYield as PeerWait
from agentbot.interfaces import (
    ProtocolSandbox,
    SandboxError,
    SandboxManager,
)

from agentbot_control.approvals import ActionArbiter, Approvals
from agentbot_control.composition import (
    compose_runtime,
)
from agentbot_control.dispatch import GuardedSandbox
from agentbot_control.event_store import EventStore, identifier, protected, sanitized, stamp
from agentbot_control.policies import Policies
from agentbot_control.process_lock import ProcessLock
from agentbot_control.run_streamer import RunStreamer
from agentbot_control.schemas import CAPABILITIES, Conflict

logger = logging.getLogger("AgentBotControlRuntime")


class Runtime:
    computers: Computers
    files: Files
    terminals: Terminals
    autopilot: Autopilot
    control: Control
    lifecycle: Lifecycle
    workspaces: Workspaces
    groups: Groups
    toolkit: Toolkit
    tools: ToolLibraries
    channels: Channels
    workflow_imports: WorkflowImports
    workspace_deletions: WorkspaceDeletions
    routines: Routines
    windows: WindowsComputers
    cloud: CloudComputers
    sandboxes: SandboxManager
    services: Services

    def __init__(
        self,
        kernel,
        catalog,
        path: Path,
        *,
        approval_timeout=120,
        run_timeout=900,
        retention_days=30,
        blob_limit=256 * 1024 * 1024,
    ):
        self.kernel, self.catalog = kernel, catalog
        self.workspace_features = os.getenv("CONTROL_WORKSPACE_FEATURES", "1") != "0"
        self.capabilities = dict(CAPABILITIES)
        if not self.workspace_features:
            for key in (
                "remote_control",
                "filesystem",
                "pty",
                "health",
                "capture_metadata",
                "lifecycle",
                "workspaces",
                "groups",
                "toolkit",
                "routines",
            ):
                self.capabilities[key] = False
        self.store = EventStore(
            path,
            retention_days=retention_days,
            blob_limit=blob_limit,
            capabilities=self.capabilities,
            db=catalog.db,
        )
        self.policies = Policies(self.store, catalog)
        self.approvals = Approvals(self.store, self.policies)
        self.action_locks = {}
        self.lock = ProcessLock(path.with_suffix(".runtime.lock"))
        self.approval_timeout, self.run_timeout = approval_timeout, run_timeout
        self.tasks = {}
        self.streamers = {}
        self.guards = {}
        self.creations = {}
        self.started = set()
        self.bot_locks = {}
        self.accepting = False
        self.users = 0
        compose_runtime(self)

    def ensure(self, bot):
        # Import once; old JSON stays untouched as a migration/rollback source.
        self.store.ensure_bot(bot, self.kernel.sessions.load(bot.id))
        self.tools.ensure(bot)
        with self.store.transaction() as db:
            self.channels.sync_bot(db, bot)

    def mutex(self, bot_id):
        return self.bot_locks.setdefault(bot_id, asyncio.Lock())

    async def startup(self):
        return await lifecycle.startup(self)

    def bind(self, computer):
        return lifecycle.bind(self, computer)

    async def migrate_legacy(self, bot):
        return await lifecycle.migrate_legacy(self, bot)
        # Reconciliation stops this precisely mapped container while retaining its files.

    async def shutdown(self):
        return await lifecycle.shutdown(self)

    async def start(
        self,
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
        return await execution.start(
            self,
            user,
            bot,
            request_id,
            prompt,
            trigger,
            attachment_ids,
            program,
            resume_sid,
            allowed_policy_id,
            run_mode,
            channel_delivery_id,
        )

    async def _execute(self, bot, response, prompt, context, model, streamer, program=None):
        return await execution._execute(
            self, bot, response, prompt, context, model, streamer, program
        )

    async def _communication(self, bot, prompt, context, model, streamer, sandbox):
        adapter = self.kernel.registry.resolve(bot.framework)
        await adapter.initialize(
            sandbox=sandbox,
            memory_context=context,
            state_streamer=streamer,
            instructions=bot.instructions,
            model=model,
        )
        async for frame in adapter.execute_step(prompt):
            yield frame

    async def decide(self, user, bot_id, aid, command):
        self.workspaces.bot(user.id, bot_id, "write")
        pending = self.approvals.pending_action(bot_id, aid)
        if pending and command.decision == "approve":
            streamer = self.streamers.get(pending["run_id"])
            if streamer and streamer.action_handler and json.loads(pending["context"]):
                original = json.loads(pending["context"])
                arguments = self.policies.open(pending["arguments_sealed"])
                try:
                    current = await streamer.action_handler.context(pending["name"], arguments)
                except asyncio.CancelledError:
                    if not streamer.action_handler.guard.stopping:
                        raise
                    current = None
                except Exception:
                    current = None
                if current != original:
                    self.approvals.invalidate(aid)
        result = self.approvals.decision(
            bot_id, aid, command.request_id, command.decision, command.revision, user.id
        )
        streamer = self.streamers.get(result["run_id"])
        if streamer and result["status"] != "pending":
            streamer.resolve(aid, result["status"] == "approved")
        return result

    def stop(self, bot_id, rid, request_id, *, cancel_channel=True):
        return cleanup.stop(self, bot_id, rid, request_id, cancel_channel=cancel_channel)

    async def close(self, bot_id, request_id, expected=None, idle_before=None, *, actor=None):
        return await cleanup.close(self, bot_id, request_id, expected, idle_before, actor=actor)

    async def sweep(self, idle_seconds):
        return await cleanup.sweep(self, idle_seconds)


from agentbot_control.runtime import cleanup, execution, lifecycle

__all__ = [
    "ActionArbiter",
    "Approvals",
    "CAPABILITIES",
    "CommunicationSandbox",
    "Conflict",
    "EventStore",
    "GuardedSandbox",
    "Path",
    "PeerWait",
    "Policies",
    "ProcessLock",
    "ProtocolSandbox",
    "RunStreamer",
    "Runtime",
    "SandboxError",
    "SandboxManager",
    "TYPE_CHECKING",
    "UTC",
    "asyncio",
    "cleanup",
    "compose_runtime",
    "datetime",
    "execution",
    "identifier",
    "json",
    "lifecycle",
    "logger",
    "logging",
    "os",
    "perf_counter",
    "protected",
    "sanitized",
    "stamp",
    "timedelta",
]
