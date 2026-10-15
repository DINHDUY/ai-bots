"""HTTP for the workspace computer setting and its lifecycle."""

from __future__ import annotations

from fastapi import Request

from agentbot_control.shared_computers.lifecycle import WorkspaceLifecycle
from agentbot_control.shared_computers.settings import UpdateComputer, update, view
from agentbot_control.transport import body


def register_routes(app):
    shared = app.state.runtime.shared_computers

    @app.get("/api/workspaces/{wid}/computer")
    async def read(wid: str, request: Request):
        role = shared.workspaces.role(shared.workspaces.user(request).id, wid)
        return view(shared.store, wid, role)

    @app.put("/api/workspaces/{wid}/computer")
    async def change(wid: str, request: Request):
        user = shared.workspaces.user(request)
        shared.workspaces.role(user.id, wid, owner=True)
        command = await body(request, UpdateComputer)
        return update(shared.store, shared.cloud, wid, user.id, command)

    @app.post("/api/workspaces/{wid}/computer/lifecycle")
    async def lifecycle(wid: str, request: Request):
        user = shared.workspaces.user(request)
        shared.workspaces.role(user.id, wid, owner=True)
        command = await body(request, WorkspaceLifecycle)
        async with shared.mutex("computer:" + wid):
            settings = shared.lifecycle._settings(wid)
            if settings["mode"] != "shared":
                from agentbot_control.schemas import Conflict

                raise Conflict(
                    "Turn on the shared workspace computer before managing it.",
                    code="workspace_computer",
                )
            if settings["provider"] == "docker":
                return await shared.lifecycle.command(wid, user.id, command)
            return await shared.cloud_ops.command(wid, user, command)
