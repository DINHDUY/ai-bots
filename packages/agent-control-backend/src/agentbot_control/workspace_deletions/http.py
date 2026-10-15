"""Authenticated deletion and recovery routes."""

from fastapi import FastAPI, Query, Request, Response

from agentbot_control.transport import body
from agentbot_control.workspace_deletions.schemas import (
    DeleteCommand,
    DeletionHistory,
    DeletionPreview,
    DeletionResult,
    EmptyCommand,
)
from agentbot_control.workspace_deletions.service import WorkspaceDeletions


def register_routes(app: FastAPI) -> None:
    service: WorkspaceDeletions = app.state.services.workspace_deletions
    workspaces = app.state.services.workspaces

    @app.get("/api/workspaces/{wid}/deletion-preview", response_model=DeletionPreview)
    async def deletion_preview(wid: str, request: Request):
        return await service.preview(workspaces.user(request).id, wid)

    @app.post("/api/workspaces/{wid}/deletions", response_model=DeletionResult)
    async def delete_workspace(wid: str, request: Request, response: Response):
        result = await service.delete(
            workspaces.user(request).id, wid, await body(request, DeleteCommand)
        )
        response.status_code = 200 if result.cleanup.state == "complete" else 202
        return result

    @app.get("/api/workspace-deletions", response_model=DeletionHistory)
    async def history(request: Request, cursor: int = Query(default=0, ge=0, le=100000)):
        return await service.history(workspaces.user(request).id, cursor)

    @app.get("/api/workspace-deletions/{request_id}", response_model=DeletionResult)
    async def receipt(request_id: str, request: Request):
        return await service.get(workspaces.user(request).id, request_id)

    @app.post("/api/workspace-deletions/{request_id}/retry-cleanup", response_model=DeletionResult)
    async def retry(request_id: str, request: Request):
        owner = workspaces.user(request).id
        await body(request, EmptyCommand)
        return await service.retry(owner, request_id)
