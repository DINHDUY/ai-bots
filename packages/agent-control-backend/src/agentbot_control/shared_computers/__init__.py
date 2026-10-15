"""One optional computer shared by the eligible bots in a workspace."""

from __future__ import annotations

from agentbot_control.shared_computers.cloud import SharedCloud
from agentbot_control.shared_computers.lifecycle import SharedLifecycle
from agentbot_control.shared_computers.resolution import bot_blocked


class SharedComputers:
    def __init__(
        self, store, *, workspaces, kernel, action_locks, bind, control, mutex, stop, tasks, cloud
    ):
        self.store = store
        self.workspaces = workspaces
        self.kernel = kernel
        self.cloud = cloud
        self.mutex = mutex
        self.lifecycle = SharedLifecycle(
            store,
            kernel=kernel,
            action_locks=action_locks,
            bind=bind,
            control=control,
            stop=stop,
            tasks=tasks,
        )
        self.cloud_ops = SharedCloud(store, cloud)

    def blocks(self, bot_id) -> bool:
        return bot_blocked(self.store, bot_id)

    async def close_idle(self, computer):
        if not computer.get("workspace_id"):
            return None
        if self.lifecycle._settings(computer["workspace_id"])["provider"] != "docker":
            return {"status": "retained", "session_id": computer["id"]}
        return await self.lifecycle.close_idle(computer["workspace_id"], computer["id"])
