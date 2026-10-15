from __future__ import annotations

from fastapi import HTTPException, Request

from agentbot_control.event_store import (
    identifier,
)
from agentbot_control.groups import GroupDefinition, GroupTask
from agentbot_control.schemas import Conflict
from agentbot_control.transport import body


def register_group_routes(app):
    service = app.state.runtime.groups

    @app.get("/api/workspaces/{wid}/groups")
    async def listing(wid: str, request: Request):
        uid = app.state.runtime.workspaces.user(request).id
        app.state.runtime.workspaces.role(uid, wid)
        with service.store.transaction() as db:
            ids = [r[0] for r in db.execute("SELECT id FROM groups WHERE workspace_id=?", (wid,))]
        return [service.get(uid, gid) for gid in ids]

    @app.post("/api/workspaces/{wid}/groups")
    async def create(wid: str, request: Request):
        uid = app.state.runtime.workspaces.user(request).id
        app.state.runtime.workspaces.role(uid, wid, owner=True)
        command = await body(request, GroupDefinition)
        for bid in command.bot_ids:
            app.state.runtime.workspaces.bot(uid, bid)
            with service.store.transaction() as db:
                if (
                    db.execute(
                        "SELECT workspace_id FROM bot_streams WHERE bot_id=?", (bid,)
                    ).fetchone()[0]
                    != wid
                ):
                    raise Conflict("Group members must share one workspace.")
        gid = identifier("group")
        with service.store.transaction() as db:
            db.execute(
                "INSERT INTO groups(id,workspace_id,name) VALUES (?,?,?)",
                (gid, wid, command.name),
            )
            db.executemany(
                "INSERT INTO group_members VALUES (?,?)",
                [(gid, bid) for bid in set(command.bot_ids)],
            )
        return service.get(uid, gid)

    @app.get("/api/groups/{gid}")
    async def detail(gid: str, request: Request):
        uid = app.state.runtime.workspaces.user(request).id
        group = service.get(uid, gid)
        with service.store.transaction() as db:
            messages = [
                dict(r)
                for r in db.execute(
                    "SELECT * FROM group_messages WHERE group_id=? ORDER BY created_at DESC LIMIT 200",
                    (gid,),
                )
            ]
            handoffs = [
                dict(r)
                for r in db.execute(
                    "SELECT * FROM handoffs WHERE group_id=? ORDER BY created_at DESC LIMIT 100",
                    (gid,),
                )
            ]
        return {**group, "messages": list(reversed(messages)), "handoffs": handoffs}

    @app.patch("/api/groups/{gid}")
    async def update(gid: str, request: Request):
        uid = app.state.runtime.workspaces.user(request).id
        group = service.get(uid, gid)
        app.state.runtime.workspaces.role(uid, group["workspace_id"], owner=True)
        command = await body(request, GroupDefinition)
        for bid in command.bot_ids:
            app.state.runtime.workspaces.bot(uid, bid)
            with service.store.transaction() as db:
                if (
                    db.execute(
                        "SELECT workspace_id FROM bot_streams WHERE bot_id=?", (bid,)
                    ).fetchone()[0]
                    != group["workspace_id"]
                ):
                    raise Conflict("Group members must share one workspace.")
        with service.store.transaction() as db:
            if not db.execute(
                "UPDATE groups SET name=?,revision=revision+1 WHERE id=? AND revision=?",
                (command.name, gid, command.revision),
            ).rowcount:
                raise Conflict("Group changed in another tab.")
            db.execute("DELETE FROM group_members WHERE group_id=?", (gid,))
            db.executemany(
                "INSERT INTO group_members VALUES (?,?)",
                [(gid, bid) for bid in set(command.bot_ids)],
            )
        return service.get(uid, gid)

    @app.delete("/api/groups/{gid}")
    async def remove(gid: str, request: Request):
        uid = app.state.runtime.workspaces.user(request).id
        group = service.get(uid, gid)
        app.state.runtime.workspaces.role(uid, group["workspace_id"], owner=True)
        with service.store.transaction() as db:
            runs = db.execute(
                "SELECT target_bot_id,target_run_id FROM handoffs WHERE group_id=? AND state='running'",
                (gid,),
            ).fetchall()
        for run in runs:
            if service.store.active(run[0]):
                app.state.runtime.stop(run[0], run[1], identifier("group_removed"))
        with service.store.transaction() as db:
            db.execute("DELETE FROM groups WHERE id=?", (gid,))
        return {"status": "deleted"}

    @app.post("/api/groups/{gid}/messages")
    async def send(gid: str, request: Request):
        return service.submit(
            app.state.runtime.workspaces.user(request).id,
            gid,
            await body(request, GroupTask),
        )

    @app.delete("/api/groups/{gid}/handoffs/{hid}")
    async def cancel(gid: str, hid: str, request: Request):
        uid = app.state.runtime.workspaces.user(request).id
        service.get(uid, gid, True)
        with service.store.transaction() as db:
            row = db.execute(
                "SELECT * FROM handoffs WHERE id=? AND group_id=?", (hid, gid)
            ).fetchone()
            if not row:
                raise HTTPException(404, "Handoff not found.")
            db.execute("UPDATE handoffs SET state='cancelled' WHERE id=?", (hid,))
        if row["target_run_id"] and service.store.active(row["target_bot_id"]):
            app.state.runtime.stop(
                row["target_bot_id"], row["target_run_id"], identifier("handoff_cancel")
            )
        return {"state": "cancelled"}
