from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Literal

from fastapi import HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse

from agentbot_control.capture_retention import CapturePolicy
from agentbot_control.event_store import identifier, packed
from agentbot_control.repositories.workspaces import create as create_workspace
from agentbot_control.schemas import Conflict
from agentbot_control.transport import body
from agentbot_control.workspaces import Grant, Member, Preferences, ReadCursor, Share, WorkspaceName


def register_workspace_routes(app):
    service = app.state.runtime.workspaces

    @app.get("/api/workspaces/{wid}/capture-retention")
    async def capture_retention(wid: str, request: Request):
        role = service.role(service.user(request).id, wid)
        return {**service.store.captures.settings(wid), "role": role}

    @app.post("/api/workspaces/{wid}/capture-retention/preview")
    async def preview_retention(wid: str, request: Request, command: CapturePolicy):
        service.role(service.user(request).id, wid, owner=True)
        return service.store.captures.preview(wid, command)

    @app.patch("/api/workspaces/{wid}/capture-retention")
    async def update_retention(wid: str, request: Request, command: CapturePolicy):
        uid = service.user(request).id
        service.role(uid, wid, owner=True)
        return {**service.store.captures.configure(wid, uid, command), "role": "owner"}

    @app.get("/api/workspaces/{wid}/diagnostics")
    async def diagnostics(wid: str, request: Request):
        service.role(service.user(request).id, wid, owner=True)
        with service.store.transaction() as db:
            runs = db.execute(
                "SELECT COUNT(*) FROM runs r JOIN bot_streams b ON b.bot_id=r.bot_id WHERE b.workspace_id=? AND r.status IN ('preparing','running','awaiting_approval','stopping')",
                (wid,),
            ).fetchone()[0]
            pending = db.execute(
                "SELECT COUNT(*),MIN(a.created_at) FROM approvals a JOIN bot_streams b ON b.bot_id=a.bot_id WHERE b.workspace_id=? AND a.status='pending'",
                (wid,),
            ).fetchone()
            health = db.execute(
                "SELECT MIN(h.observed_at) FROM computer_health h JOIN computer_sessions s ON s.id=h.session_id JOIN bot_streams b ON b.bot_id=s.bot_id WHERE b.workspace_id=? AND s.status='running'",
                (wid,),
            ).fetchone()[0]
            storage = db.execute(
                "SELECT COALESCE(SUM(size),0) FROM (SELECT size FROM capture_storage WHERE workspace_id=? AND state!='removed' UNION ALL SELECT f.size FROM file_blobs f JOIN bot_streams b ON b.bot_id=f.bot_id WHERE b.workspace_id=?)",
                (wid, wid),
            ).fetchone()[0]
            states = [
                dict(r)
                for r in db.execute(
                    "SELECT s.status,COUNT(*) AS count FROM computer_sessions s JOIN bot_streams b ON b.bot_id=s.bot_id WHERE b.workspace_id=? GROUP BY s.status",
                    (wid,),
                )
            ]
            scheduler = db.execute(
                "SELECT MIN(next_at) FROM routines WHERE workspace_id=? AND enabled=1 AND deleted=0",
                (wid,),
            ).fetchone()[0]
            jobs = [
                dict(r)
                for r in db.execute(
                    "SELECT j.state,COUNT(*) AS count FROM routine_jobs j JOIN routines r ON r.id=j.routine_id WHERE r.workspace_id=? GROUP BY j.state",
                    (wid,),
                )
            ]
            streams = [
                dict(r)
                for r in db.execute(
                    "SELECT bot_id,seq,floor_seq FROM bot_streams WHERE workspace_id=?",
                    (wid,),
                )
            ]
            releasing = db.execute(
                "SELECT COUNT(*) FROM control_leases l JOIN bot_streams b ON b.bot_id=l.bot_id WHERE b.workspace_id=? AND l.status='releasing'",
                (wid,),
            ).fetchone()[0]
        now = datetime.now(UTC)

        def age(value):
            return max(0, (now - datetime.fromisoformat(value)).total_seconds()) if value else None

        return {
            "active_runs": runs,
            "pending_approvals": pending[0],
            "oldest_approval_seconds": age(pending[1]),
            "oldest_health_seconds": age(health),
            "storage_bytes": storage,
            "storage_limit_bytes": service.store.blob_limit,
            "computers": states,
            "releasing_leases": releasing,
            "scheduler_lag_seconds": age(scheduler),
            "jobs": jobs,
            "streams": streams,
            "single_process": True,
            "workers": service.store.health.snapshot(),
            "database": {
                "pending": service.store.database.pending,
                "completed": service.store.database.jobs_completed,
                "queue_seconds_total": service.store.database.queue_seconds,
                "work_seconds_total": service.store.database.work_seconds,
            },
        }

    @app.get("/api/workspaces")
    async def workspaces(request: Request):
        user = service.user(request)
        with service.store.transaction() as db:
            return [
                dict(r)
                for r in db.execute(
                    "SELECT w.id,w.owner_id,w.name,m.role FROM workspaces w JOIN workspace_members m ON m.workspace_id=w.id WHERE m.user_id=? AND w.deleted_at IS NULL",
                    (user.id,),
                )
            ]

    @app.post("/api/workspaces")
    async def create(request: Request):
        user, command = service.user(request), await body(request, WorkspaceName)
        wid = identifier("workspace")
        with service.store.transaction() as db:
            create_workspace(db, wid, user.id, command.name)
            app.state.runtime.channels._channel(db, wid)
        return {"id": wid, "name": command.name, "role": "owner"}

    @app.get("/api/workspaces/{wid}/members")
    async def members(wid: str, request: Request):
        service.role(service.user(request).id, wid, owner=True)
        with service.store.transaction() as db:
            return [
                dict(r)
                for r in db.execute(
                    "SELECT m.user_id,u.username,m.role FROM workspace_members m JOIN users u ON u.id=m.user_id WHERE workspace_id=?",
                    (wid,),
                )
            ]

    @app.post("/api/workspaces/{wid}/members")
    async def member(wid: str, request: Request):
        service.role(service.user(request).id, wid, owner=True)
        command = await body(request, Member)
        uid = service.recipient(command.username)
        with service.store.transaction() as db:
            old = db.execute(
                "SELECT role FROM workspace_members WHERE workspace_id=? AND user_id=?",
                (wid, uid),
            ).fetchone()
            if old and old[0] == "owner":
                raise Conflict("Workspace ownership cannot be removed.")
            db.execute(
                "DELETE FROM execution_grants WHERE user_id=? AND bot_id IN (SELECT bot_id FROM bot_streams WHERE workspace_id=?)",
                (uid, wid),
            )
            if command.role == "remove":
                db.execute(
                    "DELETE FROM workspace_members WHERE workspace_id=? AND user_id=?",
                    (wid, uid),
                )
            else:
                db.execute(
                    "INSERT INTO workspace_members VALUES (?,?,?) ON CONFLICT(workspace_id,user_id) DO UPDATE SET role=excluded.role",
                    (wid, uid, command.role),
                )
        return {"status": "updated"}

    @app.post("/api/bots/{bot_id}/execution-grants")
    async def execution(bot_id: str, request: Request):
        service.bot(service.user(request).id, bot_id, "owner")
        command = await body(request, Grant)
        uid = service.recipient(command.username)
        service.bot(uid, bot_id)
        with service.store.transaction() as db:
            if command.enabled:
                db.execute("INSERT OR IGNORE INTO execution_grants VALUES (?,?)", (bot_id, uid))
            else:
                db.execute(
                    "DELETE FROM execution_grants WHERE bot_id=? AND user_id=?",
                    (bot_id, uid),
                )
        return {"status": "updated"}

    @app.post("/api/bots/{bot_id}/shares")
    async def share(bot_id: str, request: Request):
        bot = service.bot(service.user(request).id, bot_id, "owner")
        if bot.framework == "ufo":
            raise HTTPException(403, "Personal Windows desktop history cannot be shared.")
        command = await body(request, Share)
        if command.session_id:
            computer = service.store.computer(bot_id)
            if not computer or computer["id"] != command.session_id:
                raise Conflict("Share must select the current session.")
        if command.surfaces and not command.session_id:
            raise Conflict("Live surfaces require a selected session.")
        for aid in command.artifacts:
            if not app.state.runtime.files.blobs.get(bot_id, aid):
                raise Conflict("Selected artifact is not available on this bot.")
        uid, gid = service.recipient(command.username), identifier("share")
        expiry = (datetime.now(UTC) + timedelta(hours=command.hours)).isoformat()
        with service.store.transaction() as db:
            db.execute(
                "INSERT INTO share_grants VALUES (?,?,?,?,?,?,?,0)",
                (
                    gid,
                    bot_id,
                    command.session_id,
                    uid,
                    packed(command.surfaces),
                    packed(command.artifacts),
                    expiry,
                ),
            )
        return {"id": gid, "url": "/#/shares/" + gid, "expires_at": expiry}

    @app.delete("/api/bots/{bot_id}/shares/{gid}")
    async def revoke(bot_id: str, gid: str, request: Request):
        service.bot(service.user(request).id, bot_id, "owner")
        with service.store.transaction() as db:
            db.execute(
                "UPDATE share_grants SET revoked=1 WHERE id=? AND bot_id=?",
                (gid, bot_id),
            )
        return {"status": "revoked"}

    @app.get("/api/shares/{gid}")
    async def shared(gid: str, request: Request):
        grant = service.share(service.user(request).id, gid)
        captures = []
        for surface in json.loads(grant["surfaces"]):
            captures.extend(
                [
                    {**r, "url": f"/api/shares/{gid}/captures/{r['capture_id']}"}
                    for r in app.state.runtime.computers.history(
                        grant["bot_id"], surface, session_id=grant["session_id"]
                    )
                    if r["session_id"] == grant["session_id"]
                ][:1]
            )
        return {
            "id": gid,
            "expires_at": grant["expires_at"],
            "captures": captures,
            "artifacts": [
                {"id": aid, "url": f"/api/shares/{gid}/artifacts/{aid}"}
                for aid in json.loads(grant["artifacts"])
            ],
        }

    @app.get("/api/shares/{gid}/{kind}/{rid}")
    async def content(gid: str, kind: Literal["captures", "artifacts"], rid: str, request: Request):
        grant = service.share(service.user(request).id, gid)

        def response(path, media_type, filename=None):
            if not path.is_file():
                raise HTTPException(404, "Shared resource expired or unavailable.")
            headers = dict(FileResponse(path, media_type=media_type, filename=filename).headers)
            headers.update(
                {
                    "Cache-Control": "private, no-store",
                    "X-Content-Type-Options": "nosniff",
                    "Content-Length": str(path.stat().st_size),
                }
            )

            async def chunks():
                with path.open("rb") as stream:
                    while chunk := stream.read(65536):
                        service.share(service.user(request).id, gid)
                        yield chunk

            return StreamingResponse(chunks(), media_type=media_type, headers=headers)

        if kind == "artifacts" and rid in json.loads(grant["artifacts"]):
            retained = app.state.runtime.files.blobs.get(grant["bot_id"], rid)
            if not retained:
                raise HTTPException(404, "Shared artifact expired or unavailable.")
            record, path = retained
            return response(
                path,
                filename=record["path"].rsplit("/", 1)[-1],
                media_type="application/octet-stream",
            )
        if kind == "captures":
            with service.store.transaction() as db:
                row = db.execute(
                    "SELECT * FROM capture_records WHERE id=? AND bot_id=? AND session_id=?",
                    (rid, grant["bot_id"], grant["session_id"]),
                ).fetchone()
            if row and json.loads(row["metadata"] or "{}").get("surface_kind") in json.loads(
                grant["surfaces"]
            ):
                raw = service.store.captures.read(grant["bot_id"], rid)
                if raw is None:
                    raise HTTPException(404, "Capture unavailable or expired.")

                async def capture_chunks():
                    for offset in range(0, len(raw), 65536):
                        service.share(service.user(request).id, gid)
                        yield raw[offset : offset + 65536]

                return StreamingResponse(
                    capture_chunks(),
                    media_type="image/png",
                    headers={
                        "Cache-Control": "private, no-store",
                        "X-Content-Type-Options": "nosniff",
                        "Content-Length": str(len(raw)),
                    },
                )
        raise HTTPException(404, "Resource not shared.")

    @app.get("/api/preferences")
    async def preferences(request: Request):
        uid = service.user(request).id
        with service.store.transaction() as db:
            row = db.execute("SELECT * FROM user_preferences WHERE user_id=?", (uid,)).fetchone()
        return (
            {**json.loads(row["data"]), "revision": row["revision"]}
            if row
            else Preferences(revision=0).model_dump()
        )

    @app.post("/api/preferences")
    async def save_preferences(request: Request):
        uid, command = service.user(request).id, await body(request, Preferences)
        if command.workspace_id:
            service.role(uid, command.workspace_id)
        if any(len(v) > 80 for v in command.folders.values()) or any(
            v < 0 for v in command.read_cursors.values()
        ):
            raise HTTPException(422, "Invalid preference value.")
        with service.store.transaction() as db:
            row = db.execute(
                "SELECT revision FROM user_preferences WHERE user_id=?", (uid,)
            ).fetchone()
            if (row[0] if row else 0) != command.revision:
                raise Conflict("Preferences changed in another tab. Reload before saving.")
            data = command.model_dump(exclude={"revision"})
            db.execute(
                "INSERT INTO user_preferences VALUES (?,?,?) ON CONFLICT(user_id) DO UPDATE SET revision=excluded.revision,data=excluded.data",
                (uid, command.revision + 1, packed(data)),
            )
        return {**data, "revision": command.revision + 1}

    @app.post("/api/bots/{bot_id}/read-cursor")
    async def read_cursor(bot_id: str, request: Request):
        uid = service.user(request).id
        service.bot(uid, bot_id)
        command = await body(request, ReadCursor)
        with service.store.transaction() as db:
            latest = db.execute("SELECT seq FROM bot_streams WHERE bot_id=?", (bot_id,)).fetchone()[
                0
            ]
            if command.sequence > latest:
                raise Conflict("Read cursor exceeds available history.")
            row = db.execute("SELECT * FROM user_preferences WHERE user_id=?", (uid,)).fetchone()
            data = (
                json.loads(row["data"])
                if row
                else Preferences(revision=0).model_dump(exclude={"revision"})
            )
            revision = row["revision"] if row else 0
            cursors = data.setdefault("read_cursors", {})
            if command.sequence > cursors.get(bot_id, 0):
                if bot_id not in cursors and len(cursors) >= 200:
                    cursors.pop(next(iter(cursors)))
                cursors[bot_id] = command.sequence
                revision += 1
                db.execute(
                    "INSERT INTO user_preferences VALUES (?,?,?) ON CONFLICT(user_id) DO UPDATE SET revision=excluded.revision,data=excluded.data",
                    (uid, revision, packed(data)),
                )
        return {**data, "revision": revision}

    @app.get("/api/notifications")
    async def notifications(request: Request, before: str = "9999"):
        uid = service.user(request).id
        with service.store.transaction() as db:
            return [
                {**dict(r), "url": "/#/bots/" + r["bot_id"]}
                for r in db.execute(
                    "SELECT n.* FROM notifications n JOIN bot_streams b ON b.bot_id=n.bot_id JOIN workspace_members m ON m.workspace_id=b.workspace_id AND m.user_id=n.user_id WHERE n.user_id=? AND n.created_at<? ORDER BY n.created_at DESC LIMIT 100",
                    (uid, before),
                )
            ]

    @app.post("/api/notifications/{nid}/read")
    async def mark_read(nid: str, request: Request):
        uid = service.user(request).id
        with service.store.transaction() as db:
            db.execute("UPDATE notifications SET read=1 WHERE id=? AND user_id=?", (nid, uid))
        return {"status": "read"}

    @app.get("/api/workspaces/{wid}/search")
    async def search(
        wid: str,
        request: Request,
        q: str,
        kind: Literal["all", "bot", "message", "skill", "routine", "file"] = "all",
        cursor: int = 0,
    ):
        uid = service.user(request).id
        service.role(uid, wid)
        if not 1 <= len(q) <= 200 or not 0 <= cursor <= 10000:
            raise HTTPException(422, "Invalid search.")
        query = '"' + q.replace('"', '""') + '"'
        with service.store.transaction() as db:
            # FTS never contains credentials or file contents. Eligibility is checked in SQL at read time.
            db.execute("DELETE FROM search_index WHERE kind IN ('bot','message')")
            db.execute("INSERT INTO search_index SELECT id,id,'bot',name,instructions FROM bots")
            db.execute(
                "INSERT INTO search_index SELECT id,bot_id,'message',role,content FROM messages"
            )
            rows = db.execute(
                "SELECT f.resource_id,f.bot_id,f.kind,f.title,snippet(search_index,4,'[',']','...',20) AS snippet FROM search_index f JOIN bot_streams b ON b.bot_id=f.bot_id JOIN bots c ON c.id=f.bot_id JOIN workspace_members m ON m.workspace_id=b.workspace_id WHERE search_index MATCH ? AND b.workspace_id=? AND m.user_id=? AND (c.framework!='ufo' OR c.owner_id=?) AND (?='all' OR f.kind=?) LIMIT 50 OFFSET ?",
                (query, wid, uid, uid, kind, kind, cursor),
            ).fetchall()
        return {
            "hits": [dict(r) for r in rows],
            "next_cursor": cursor + 50 if len(rows) == 50 else None,
        }
