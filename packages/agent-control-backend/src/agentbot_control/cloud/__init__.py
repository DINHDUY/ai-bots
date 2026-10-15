"""Persisted cloud selection, ownership and asynchronous lifecycle reconciliation.

No Azure calls occur in inspection, admission, or configuration request handlers.
Every mutation has a committed target and phase before it can leave this process.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agentbot_control.control import Control
    from agentbot_control.event_store import EventStore
    from agentbot_control.policies import Policies
    from agentbot_control.ports import StopRun
    from agentbot_control.store import Bot
    from agentbot_control.workspaces import Workspaces

import json
import secrets
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Literal

from agentbot.interfaces import SandboxError, SandboxManager
from agentbot.sandbox.remote import RemoteSandbox
from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import Field

from agentbot_control.compute_profiles import ComputeProfile, load_profiles
from agentbot_control.computer_agents import ComputerAgents
from agentbot_control.event_store import fingerprint, identifier, packed, stamp
from agentbot_control.lifecycle import LifecycleCommand
from agentbot_control.providers.azure import AzureDriver, CloudError
from agentbot_control.providers.bootstrap import script
from agentbot_control.repositories import admission
from agentbot_control.schemas import Command, Conflict
from agentbot_control.transport import body

TERMINAL = {"completed", "failed", "outcome_unknown"}
CLOUD = {"azure_ml_compute_instance", "azure_vm"}


def later(seconds):
    return (datetime.now(UTC) + timedelta(seconds=seconds)).isoformat()


class SelectCloud(Command):
    provider: Literal["docker", "azure_ml_compute_instance", "azure_vm"]
    profile_id: str | None = Field(default=None, max_length=64)
    ownership: Literal["attached", "managed"] = "attached"
    expected_revision: int = Field(ge=0)


class AttachCloud(Command):
    resource_id: str = Field(min_length=1, max_length=1024)
    expected_revision: int = Field(ge=0)
    generation: int = Field(ge=0)


class EnrollHost(Command):
    host_key: str = Field(pattern=r"^[a-f0-9]{64}$")


class ComputeGrant(Command):
    username: str = Field(min_length=1, max_length=100)
    enabled: bool


class CloudComputers:
    def __init__(
        self,
        store: EventStore,
        *,
        control: Control,
        ensure: Callable[[Bot], None],
        mutex: Callable[[str], asyncio.Lock],
        policies: Policies,
        stop: StopRun,
        tasks: dict[str, asyncio.Task],
        workspaces: Workspaces,
    ) -> None:
        self.store = store
        self.control = control
        self.ensure = ensure
        self.mutex = mutex
        self.policies = policies
        self.stop = stop
        self.tasks = tasks
        self.workspaces = workspaces
        self.profiles = load_profiles(self.store)
        self.agents = ComputerAgents(self)
        self.drivers, self.clients, self.workers = {}, {}, {}
        self.pump_task: asyncio.Task[None] | None = None
        self.last_observation = {}

    def config(self, bot_id):
        return configuration.config(self, bot_id)

    def selected(self, bot_id):
        return configuration.selected(self, bot_id)

    def binding(self, *, bot_id=None, binding_id=None, session_id=None, workspace_id=None):
        return configuration.binding(
            self,
            bot_id=bot_id,
            binding_id=binding_id,
            session_id=session_id,
            workspace_id=workspace_id,
        )

    def profile_for(self, binding):
        return configuration.profile_for(self, binding)

    def driver(self, binding):
        # A binding retains its immutable approved profile through config reloads.
        return configuration.driver(self, binding)

    def actor(self, request, bot_id):
        return configuration.actor(self, request, bot_id)

    def can_manage(self, user, bot_id, profile=None, *, administrator=False, workspace_id=None):
        return configuration.can_manage(
            self, user, bot_id, profile, administrator=administrator, workspace_id=workspace_id
        )

    def require_manage(self, user, bot_id, profile=None, **kwargs):
        return configuration.require_manage(self, user, bot_id, profile, **kwargs)

    def configured_profile(self, bot_id):
        return configuration.configured_profile(self, bot_id)

    def configuration(self, user, bot):
        return configuration.configuration(self, user, bot)

    async def select(self, user, bot, command):
        return await configuration.select(self, user, bot, command)

    def operation(self, operation_id):
        return status.operation(self, operation_id)

    def progress(self, op):
        return status.progress(self, op)

    def active_operation(self, binding_id):
        return status.active_operation(self, binding_id)

    def details(self, binding):
        return status.details(self, binding)

    def actions(self, user, bot_id):
        return status.actions(self, user, bot_id)

    def report(self, bot_id):
        return status.report(self, bot_id)

    def require_run(self, bot, user_id):
        return status.require_run(self, bot, user_id)

    def quarantine(self, binding_id, reason):
        return status.quarantine(self, binding_id, reason)

    def host_rebooted(self, binding):
        return status.host_rebooted(self, binding)

    def host_profile(self, binding):
        return status.host_profile(self, binding)

    async def admit(self, user, bot, operation, command, resource_id=None):
        return await admission_ops.admit(self, user, bot, operation, command, resource_id)

    def update(self, op, phase=None, **values):
        return observations.update(self, op, phase, **values)

    def finish(self, op, phase="completed", detail=None, code=None):
        return observations.finish(self, op, phase, detail, code)

    def submitted(self, op, response):
        return observations.submitted(self, op, response)

    async def pause(self, binding):
        return await observations.pause(self, binding)

    def verify_resource(self, binding, report):
        return observations.verify_resource(self, binding, report)

    def verify_managed_identity(self, binding, report):
        return observations.verify_managed_identity(self, binding, report)

    async def observe_binding(self, binding):
        return await observations.observe_binding(self, binding)

    async def revoke(self, binding):
        return await observations.revoke(self, binding)

    async def step(self, op):
        return await phases.step(self, op)

    async def cleanup(self, binding):
        return await lifecycle.cleanup(self, binding)

    async def loop(self):
        return await lifecycle.loop(self)

    def start(self):
        return lifecycle.start(self)

    async def shutdown(self):
        return await lifecycle.shutdown(self)

    async def retire(self, bot_id, request_id, expected=None, *, idle=False, actor=None):
        return await lifecycle.retire(self, bot_id, request_id, expected, idle=idle, actor=actor)

    def routes(self, app):
        return http.routes(self, app)


def _binding_ready(cloud, binding):
    if binding and binding.get("bot_id"):
        return cloud.report(binding["bot_id"])
    from agentbot_control.shared_computers.cloud import binding_report

    return binding_report(cloud, binding)


class CloudProviderRouter:
    def __init__(self, fallback, cloud):
        self.fallback, self.cloud = fallback, cloud
        self.bindings = {}

    def __getattr__(self, name):
        return getattr(self.fallback, name)

    def configure_scope(self, namespace, deployment):
        if isinstance(self.fallback, SandboxManager):
            self.fallback.configure_scope(namespace, deployment)

    def bind(self, sid, bot_id, generation):
        self.bindings[sid] = bot_id
        if self.cloud.binding(session_id=sid) or (bot_id and self.cloud.selected(bot_id)):
            return
        self.fallback.bind(sid, bot_id, generation)

    def is_cloud(self, sid):
        return bool(self.cloud.binding(session_id=sid)) or (
            sid in self.bindings and self.cloud.selected(self.bindings[sid])
        )

    async def legacy_candidate(self, bot_id):
        if not self.cloud.selected(bot_id) and isinstance(self.fallback, SandboxManager):
            return await self.fallback.legacy_candidate(bot_id)

    async def get_or_create(self, sid):
        return (
            await self.existing(sid)
            if self.is_cloud(sid)
            else await self.fallback.get_or_create(sid)
        )

    async def existing(self, sid):
        if not self.is_cloud(sid):
            return await self.fallback.existing(sid)
        binding = self.cloud.binding(session_id=sid)
        ready = _binding_ready(self.cloud, binding)
        if not binding or not binding["active"] or not ready["compatible"]:
            raise SandboxError(
                "Cloud computer is not ready. Explicitly attach/start it; local fallback is disabled."
            )
        client = self.cloud.clients.get(binding["id"])
        if not client or client.session_id != sid:
            client = self.cloud.clients[binding["id"]] = RemoteSandbox(
                binding, self.cloud.agents.call
            )
        return client

    async def inspect(self, sid):
        if not self.is_cloud(sid):
            return await self.fallback.inspect(sid)
        binding = self.cloud.binding(session_id=sid)
        if not binding or not binding["active"]:
            return {"lifecycle": "missing", "compatible": False, "services": {}}
        return _binding_ready(self.cloud, binding)

    async def reconcile(self, sid, uncertain=False):
        if not self.is_cloud(sid):
            return await self.fallback.reconcile(sid, uncertain)
        binding = self.cloud.binding(session_id=sid)
        if uncertain and binding:
            self.cloud.quarantine(
                binding["id"],
                "Control restarted during a run; inspect and stop the cloud computer.",
            )
        return (await self.inspect(sid))["lifecycle"]

    async def close(self, sid):
        if not self.is_cloud(sid):
            return await self.fallback.close(sid)
        raise SandboxError("Cloud retirement requires a persisted lifecycle operation.")

    async def hibernate(self, sid):
        if not self.is_cloud(sid):
            return await self.fallback.hibernate(sid)
        raise SandboxError("Explicit cloud Stop computer is required.")

    async def resume(self, sid):
        if not self.is_cloud(sid):
            return await self.fallback.resume(sid)
        raise SandboxError("Explicit cloud Start computer is required.")


from agentbot_control.cloud import (
    admission_ops,
    configuration,
    http,
    lifecycle,
    observations,
    phases,
    status,
)

__all__ = [
    "AttachCloud",
    "AzureDriver",
    "CLOUD",
    "Callable",
    "CloudComputers",
    "CloudError",
    "CloudProviderRouter",
    "Command",
    "ComputeGrant",
    "ComputeProfile",
    "ComputerAgents",
    "Conflict",
    "EnrollHost",
    "Field",
    "HTTPException",
    "JSONResponse",
    "LifecycleCommand",
    "Literal",
    "RemoteSandbox",
    "Request",
    "SandboxError",
    "SandboxManager",
    "SelectCloud",
    "SimpleNamespace",
    "TERMINAL",
    "TYPE_CHECKING",
    "UTC",
    "admission",
    "admission_ops",
    "asyncio",
    "body",
    "configuration",
    "datetime",
    "fingerprint",
    "http",
    "identifier",
    "json",
    "later",
    "lifecycle",
    "load_profiles",
    "observations",
    "packed",
    "phases",
    "script",
    "secrets",
    "stamp",
    "status",
    "timedelta",
]
