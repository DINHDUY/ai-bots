from __future__ import annotations

import asyncio

from fastapi import HTTPException, Request, WebSocket, WebSocketDisconnect

from agentbot_control.auth import COOKIE_NAME
from agentbot_control.channels import ChannelConfig, ChannelPost, Participation, ReadCursor
from agentbot_control.schemas import Conflict
from agentbot_control.transport import body


def register_channel_routes(app):
    service = app.state.runtime.channels

    def actor(request):
        service.available()
        return app.state.runtime.workspaces.user(request).id

    @app.get("/api/workspaces/{wid}/channel")
    @app.get("/api/workspaces/{wid}/channel/snapshot")
    async def snapshot(wid: str, request: Request):
        return service.snapshot(actor(request), wid)

    @app.patch("/api/workspaces/{wid}/channel")
    async def configure(wid: str, request: Request):
        return service.configure(actor(request), wid, await body(request, ChannelConfig))

    @app.get("/api/workspaces/{wid}/bots/directory")
    async def directory(wid: str, request: Request, query: str = "", offset: int = 0):
        return service.directory(actor(request), wid, query, offset)

    @app.get("/api/bots/{bid}/collaboration")
    async def participation(bid: str, request: Request):
        return service.participation(actor(request), bid)

    @app.patch("/api/bots/{bid}/collaboration")
    async def enroll(bid: str, request: Request):
        uid = actor(request)
        command = await body(request, Participation)
        with service.store.transaction() as db:
            service.enroll(db, bid, uid, command)
        app.state.runtime.tools.wake(bid)
        return service.participation(uid, bid)

    @app.get("/api/bots/{bid}/collaboration-task")
    async def task(bid: str, request: Request):
        return service.task(actor(request), bid)

    @app.get("/api/workspaces/{wid}/channel/messages")
    async def messages(wid: str, request: Request, thread_id: str | None = None, before: int = 0):
        uid = actor(request)
        if before < 0:
            raise HTTPException(422, "Invalid message cursor.")
        with service.store.transaction() as db:
            service._role(db, uid, wid)
            return service._messages(db, wid, thread_id, before)

    @app.post("/api/workspaces/{wid}/channel/messages", status_code=201)
    async def post(wid: str, request: Request):
        return service.post(actor(request), wid, await body(request, ChannelPost))

    @app.post("/api/workspaces/{wid}/channel/threads/{tid}/cancel")
    async def cancel(wid: str, tid: str, request: Request):
        return service.cancel(actor(request), wid, tid)

    @app.get("/api/workspaces/{wid}/channel/events")
    async def events(wid: str, request: Request, after_seq: int = 0):
        if after_seq < 0:
            raise HTTPException(422, "Invalid event cursor.")
        return service.events(actor(request), wid, after_seq)

    @app.post("/api/workspaces/{wid}/channel/read")
    async def read(wid: str, request: Request):
        uid, command = actor(request), await body(request, ReadCursor)
        with service.store.transaction() as db:
            service._role(db, uid, wid)
            if command.sequence > service._channel(db, wid)["seq"]:
                raise HTTPException(422, "Read cursor exceeds the current channel sequence.")
            db.execute(
                "INSERT INTO channel_read_cursors VALUES (?,?,?) ON CONFLICT(workspace_id,principal_id) DO UPDATE SET sequence=MAX(sequence,excluded.sequence)",
                (wid, uid, command.sequence),
            )
        return {"status": "read"}

    @app.get("/api/workspaces/{wid}/channel/artifacts/{gid}")
    async def artifact(wid: str, gid: str, request: Request):
        from fastapi.responses import Response

        uid = actor(request)
        with service.store.transaction() as db:
            service._role(db, uid, wid)
            grant = db.execute(
                "SELECT * FROM channel_artifact_grants WHERE id=? AND workspace_id=? AND revoked=0",
                (gid, wid),
            ).fetchone()
            if not grant:
                raise HTTPException(404, "Shared artifact unavailable.")
            item = service._artifact(db, wid, grant["published_by"], grant["blob_id"])
            if item["revision"] != grant["revision"]:
                raise Conflict("Shared artifact changed.")
        return Response(
            item["content"].encode(),
            media_type="application/octet-stream",
            headers={
                "Content-Disposition": 'attachment; filename="shared-artifact.txt"',
                "X-Content-Type-Options": "nosniff",
                "Cache-Control": "no-store",
            },
        )

    @app.post("/api/workspaces/{wid}/channel/artifacts/{gid}/revoke")
    async def revoke_artifact(wid: str, gid: str, request: Request):
        uid = actor(request)
        with service.store.transaction() as db:
            role = service._role(db, uid, wid, write=True)
            grant = db.execute(
                "SELECT * FROM channel_artifact_grants WHERE id=? AND workspace_id=?",
                (gid, wid),
            ).fetchone()
            if not grant or (grant["published_by"] != uid and role != "owner"):
                raise HTTPException(404, "Shared artifact unavailable.")
            db.execute("UPDATE channel_artifact_grants SET revoked=1 WHERE id=?", (gid,))
            service.event(db, wid, "artifact.revoked", {"grant_id": gid})
        return {"status": "revoked"}

    @app.websocket("/api/workspaces/{wid}/channel/events/ws")
    async def stream(wid: str, websocket: WebSocket):
        origin = websocket.headers.get("origin")
        if origin is not None and origin not in app.state.cors_origins:
            await websocket.close(code=1008)
            return
        await websocket.accept()
        try:
            after = int(websocket.query_params.get("after_seq", "0"))
            if after < 0:
                raise ValueError()
            while True:
                user = app.state.runtime.catalog.user_from_token(websocket.cookies.get(COOKIE_NAME))
                if not user:
                    raise HTTPException(401)
                page = service.events(user.id, wid, after)
                await websocket.send_json(page)
                after = page["next_seq"]
                if page["resync_required"]:
                    break
                try:
                    await asyncio.wait_for(websocket.receive_text(), timeout=1)
                except TimeoutError:
                    pass
        except (WebSocketDisconnect, RuntimeError):
            return
        except (HTTPException, ValueError):
            try:
                await websocket.close(code=1008)
            except (RuntimeError, WebSocketDisconnect):
                pass
