"""Authenticated import commands; browser retries use durable owner-scoped receipts."""

from fastapi import FastAPI, Request

from agentbot_control.transport import body
from agentbot_control.workflow_imports.schemas import (
    ImportCommand,
    ImportDraft,
    ImportPreview,
    ImportResult,
)
from agentbot_control.workflow_imports.service import WorkflowImports


def register_routes(app: FastAPI) -> None:
    service: WorkflowImports = app.state.services.workflow_imports
    workspaces = app.state.services.workspaces

    @app.post("/api/workflow-imports/preview", response_model=ImportPreview)
    async def preview(request: Request):
        owner = workspaces.user(request).id
        return await service.preview(owner, await body(request, ImportDraft))

    @app.post("/api/workflow-imports", response_model=ImportResult, status_code=201)
    async def commit(request: Request):
        owner = workspaces.user(request).id
        return await service.commit(owner, await body(request, ImportCommand))

    @app.get("/api/workflow-imports/{request_id}", response_model=ImportResult)
    async def receipt(request_id: str, request: Request):
        return await service.receipt(workspaces.user(request).id, request_id)
