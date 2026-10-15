"""Control-plane composition root.

The graph is assembled here. Services receive individual collaborators and
callbacks; the request boundary receives the typed Services view.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from agentbot.interfaces import SandboxManager
from agentbot_tools.ufo import UfoAgentAdapter

from agentbot_control.cloud import CloudProviderRouter
from agentbot_control.windows import ProviderRouter

if TYPE_CHECKING:
    from agentbot.kernel import EngineRuntimeManager

    from agentbot_control.approvals import Approvals
    from agentbot_control.autopilot import Autopilot
    from agentbot_control.channels import Channels
    from agentbot_control.cloud import CloudComputers
    from agentbot_control.computer import Computers
    from agentbot_control.control import Control
    from agentbot_control.event_store import EventStore
    from agentbot_control.files import Files
    from agentbot_control.groups import Groups
    from agentbot_control.lifecycle import Lifecycle
    from agentbot_control.policies import Policies
    from agentbot_control.routines import Routines
    from agentbot_control.runtime import Runtime
    from agentbot_control.store import Catalog
    from agentbot_control.terminals import Terminals
    from agentbot_control.tool_libraries import ToolLibraries
    from agentbot_control.toolkit import Toolkit
    from agentbot_control.windows import WindowsComputers
    from agentbot_control.workflow_imports.service import WorkflowImports
    from agentbot_control.workspace_deletions.service import WorkspaceDeletions
    from agentbot_control.workspaces import Workspaces


class SandboxRouter:
    """Docker, then Windows, then cloud. One object on the kernel."""

    def __init__(self, docker, windows, cloud):
        self.docker = docker
        self.inner = CloudProviderRouter(ProviderRouter(docker, windows), cloud)

    def __getattr__(self, name):
        return getattr(self.inner, name)

    def configure_scope(self, namespace, deployment):
        self.inner.configure_scope(namespace, deployment)

    def bind(self, session_id, bot_id, generation):
        self.inner.bind(session_id, bot_id, generation)

    def note_workspace(self, session_id, workspace_id):
        note = getattr(self.docker, "note_workspace", None)
        if note:
            note(session_id, workspace_id)

    async def legacy_candidate(self, bot_id):
        return await self.inner.legacy_candidate(bot_id)

    async def inspect(self, session_id):
        return await self.inner.inspect(session_id)

    async def existing(self, session_id):
        return await self.inner.existing(session_id)

    async def reconcile(self, session_id, uncertain):
        return await self.inner.reconcile(session_id, uncertain)

    async def hibernate(self, session_id):
        return await self.inner.hibernate(session_id)

    async def get_or_create(self, session_id):
        return await self.inner.get_or_create(session_id)

    async def close(self, session_id):
        return await self.inner.close(session_id)

    async def resume(self, session_id):
        return await self.inner.resume(session_id)

    def is_cloud(self, session_id):
        return self.inner.is_cloud(session_id)

    def is_windows(self, session_id):
        return self.inner.is_windows(session_id)


def attach_sandbox_router(kernel, windows, cloud) -> SandboxRouter:
    if isinstance(kernel.sandboxes, SandboxRouter):
        return kernel.sandboxes
    router = SandboxRouter(kernel.sandboxes, windows, cloud)
    kernel.sandboxes = router
    return router


def ensure_control_frameworks(kernel) -> None:
    kernel.registry.register_framework("ufo", UfoAgentAdapter)


@dataclass(frozen=True)
class Services:
    """The objects a request handler is allowed to reach."""

    kernel: EngineRuntimeManager
    catalog: Catalog
    store: EventStore
    policies: Policies
    approvals: Approvals
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
    runs: Runtime


def build_services(kernel, catalog, db_path, **settings) -> Services:
    """Construct the control plane and return its service graph.

    Imported lazily so this module can be imported from Runtime.
    """
    from agentbot_control.runtime import Runtime

    runtime = Runtime(kernel, catalog, db_path, **settings)
    return runtime.services


def compose_runtime(coordinator: Runtime) -> None:
    """Wire the graph; Runtime construction is retained as a compatibility entry point."""
    import os

    from agentbot_control.autopilot import Autopilot
    from agentbot_control.channels import Channels
    from agentbot_control.cloud import CloudComputers
    from agentbot_control.computer import Computers
    from agentbot_control.control import Control
    from agentbot_control.files import Files
    from agentbot_control.groups import Groups
    from agentbot_control.hooks import StoreHooks
    from agentbot_control.lifecycle import Lifecycle
    from agentbot_control.routines import Routines
    from agentbot_control.shared_computers import SharedComputers
    from agentbot_control.terminals import Terminals
    from agentbot_control.tool_libraries import ToolLibraries
    from agentbot_control.toolkit import Toolkit
    from agentbot_control.windows import WindowsComputers
    from agentbot_control.workspaces import Workspaces

    kernel, catalog = coordinator.kernel, coordinator.catalog
    coordinator.workspaces = Workspaces(coordinator.store, catalog)
    catalog.configure_authorization(coordinator.workspaces.bot)
    coordinator.windows = WindowsComputers(coordinator.store, coordinator.tasks)
    coordinator.toolkit = Toolkit(coordinator.store, catalog, coordinator.workspaces)
    coordinator.control = Control(
        coordinator.store,
        catalog=catalog,
        workspaces=coordinator.workspaces,
        kernel=kernel,
        windows=coordinator.windows,
        toolkit=coordinator.toolkit,
        action_locks=coordinator.action_locks,
        bind=coordinator.bind,
        mutex=coordinator.mutex,
        start=coordinator.start,
        stop=coordinator.stop,
        tasks=coordinator.tasks,
        computer_existing=lambda *args, **kwargs: coordinator.computers.existing(*args, **kwargs),
        computer_history=lambda *args, **kwargs: coordinator.computers.history(*args, **kwargs),
        close_lease=lambda lease_id: coordinator.terminals.close_lease(lease_id),
    )
    coordinator.lifecycle = Lifecycle(
        coordinator.store,
        action_locks=coordinator.action_locks,
        bind=coordinator.bind,
        control=coordinator.control,
        kernel=kernel,
        mutex=coordinator.mutex,
        stop=coordinator.stop,
        tasks=coordinator.tasks,
        windows=coordinator.windows,
    )
    coordinator.shared_computers = None
    coordinator.cloud = CloudComputers(
        coordinator.store,
        control=coordinator.control,
        ensure=coordinator.ensure,
        mutex=coordinator.mutex,
        policies=coordinator.policies,
        stop=coordinator.stop,
        tasks=coordinator.tasks,
        workspaces=coordinator.workspaces,
    )
    coordinator.shared_computers = SharedComputers(
        coordinator.store,
        workspaces=coordinator.workspaces,
        kernel=kernel,
        action_locks=coordinator.action_locks,
        bind=coordinator.bind,
        control=coordinator.control,
        mutex=coordinator.mutex,
        stop=coordinator.stop,
        tasks=coordinator.tasks,
        cloud=coordinator.cloud,
    )
    ensure_control_frameworks(kernel)
    coordinator.sandboxes = attach_sandbox_router(kernel, coordinator.windows, coordinator.cloud)
    coordinator.capabilities["cloud_computers"] = bool(coordinator.cloud.profiles)
    coordinator.capabilities["windows_computers"] = True
    coordinator.capabilities["frameworks"] = ["anthropic", "microsoft", "ufo"]
    coordinator.tools = ToolLibraries(
        coordinator.store,
        approvals=coordinator.approvals,
        catalog=catalog,
        streamers=coordinator.streamers,
        binding_changed=lambda db, bid: coordinator.channels.binding_changed(db, bid),
    )
    coordinator.capabilities["tool_libraries"] = True
    coordinator.capabilities["workspace_bot_channels"] = (
        coordinator.workspace_features and os.getenv("CONTROL_WORKSPACE_CHANNELS", "1") != "0"
    )
    coordinator.computers = Computers(
        coordinator.store,
        kernel,
        cloud=coordinator.cloud,
        lifecycle=coordinator.lifecycle,
        control=coordinator.control,
        toolkit=coordinator.toolkit,
        bind=coordinator.bind,
        action_locks=coordinator.action_locks,
        workspace_features=coordinator.workspace_features,
        ensure=coordinator.ensure,
        workspaces=coordinator.workspaces,
    )
    coordinator.files = Files(
        coordinator.store,
        coordinator.computers,
        coordinator.action_locks,
        coordinator.mutex,
        coordinator.control,
    )
    coordinator.terminals = Terminals(
        coordinator.store,
        coordinator.control,
        coordinator.computers,
        coordinator.toolkit,
        kernel,
        catalog,
    )
    coordinator.autopilot = Autopilot(
        coordinator.store, coordinator.workspaces, coordinator.approvals, coordinator.streamers
    )
    coordinator.channels = Channels(
        coordinator.store,
        accepting=lambda: coordinator.accepting,
        catalog=catalog,
        ensure=coordinator.ensure,
        files=coordinator.files,
        start=coordinator.start,
        stop=coordinator.stop,
        tools=coordinator.tools,
        workspaces=coordinator.workspaces,
        enabled=coordinator.capabilities["workspace_bot_channels"],
    )
    from agentbot_control.workflow_imports.schemas import LIMITS
    from agentbot_control.workflow_imports.service import WorkflowImports

    coordinator.capabilities["workflow_imports"] = coordinator.capabilities[
        "workspace_bot_channels"
    ]
    coordinator.capabilities["workflow_import_limits"] = LIMITS
    coordinator.workflow_imports = WorkflowImports(
        coordinator.store.database,
        catalog,
        coordinator.tools,
        coordinator.channels,
        enabled=lambda: all(
            coordinator.capabilities.get(key)
            for key in (
                "workflow_imports",
                "workspaces",
                "workspace_bot_channels",
                "tool_libraries",
            )
        ),
        known=kernel.registry.known,
    )
    from agentbot_control.workspace_deletions.service import WorkspaceDeletions

    coordinator.capabilities["workspace_deletions"] = coordinator.workspace_features
    coordinator.workspace_deletions = WorkspaceDeletions(
        coordinator.store.database,
        coordinator.store.blobs,
        kernel.sessions._directory,
        enabled=lambda: coordinator.workspace_features,
    )
    coordinator.groups = Groups(
        coordinator.store,
        channels=coordinator.channels,
        files=coordinator.files,
        start=coordinator.start,
        stop=coordinator.stop,
        workspaces=coordinator.workspaces,
    )
    coordinator.routines = Routines(
        coordinator.store,
        accepting=lambda: coordinator.accepting,
        autopilot=coordinator.autopilot,
        catalog=catalog,
        channels=coordinator.channels,
        groups=coordinator.groups,
        lifecycle=coordinator.lifecycle,
        policies=coordinator.policies,
        start=coordinator.start,
        stop=coordinator.stop,
        toolkit=coordinator.toolkit,
        workspace_features=coordinator.workspace_features,
        workspaces=coordinator.workspaces,
    )
    coordinator.store.capabilities = coordinator.capabilities
    coordinator.store.hooks = StoreHooks(
        projector=coordinator.workspaces,
        admission=coordinator.tools,
        channels=coordinator.channels,
    )
    coordinator.services = Services(
        kernel=kernel,
        catalog=catalog,
        store=coordinator.store,
        policies=coordinator.policies,
        approvals=coordinator.approvals,
        computers=coordinator.computers,
        files=coordinator.files,
        terminals=coordinator.terminals,
        autopilot=coordinator.autopilot,
        control=coordinator.control,
        lifecycle=coordinator.lifecycle,
        workspaces=coordinator.workspaces,
        groups=coordinator.groups,
        toolkit=coordinator.toolkit,
        tools=coordinator.tools,
        channels=coordinator.channels,
        routines=coordinator.routines,
        workflow_imports=coordinator.workflow_imports,
        workspace_deletions=coordinator.workspace_deletions,
        windows=coordinator.windows,
        cloud=coordinator.cloud,
        sandboxes=coordinator.sandboxes,
        runs=coordinator,
    )
    if isinstance(coordinator.sandboxes, SandboxManager):
        coordinator.sandboxes.configure_scope("control", coordinator.store.deployment)
