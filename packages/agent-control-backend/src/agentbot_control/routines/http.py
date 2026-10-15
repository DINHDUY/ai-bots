from __future__ import annotations

import hashlib
import hmac
import json
import re
import secrets
import time
from datetime import UTC, datetime

from fastapi import HTTPException, Request

from agentbot_control.event_store import identifier, packed, stamp
from agentbot_control.routines import RoutineDefinition, next_time
from agentbot_control.schemas import Command, Conflict
from agentbot_control.transport import body


def register_routine_routes(app):
    service = app.state.runtime.routines

    @app.get("/api/workspaces/{wid}/routines")
    async def listing(wid: str, request: Request):
        uid = app.state.runtime.workspaces.user(request).id
        app.state.runtime.workspaces.role(uid, wid)
        with service.store.transaction() as db:
            rows = db.execute(
                "SELECT r.id,r.version,r.enabled,r.next_at,v.definition FROM routines r JOIN routine_versions v ON v.routine_id=r.id AND v.version=r.version WHERE r.workspace_id=? AND r.deleted=0",
                (wid,),
            ).fetchall()
        return [{**dict(r), "definition": json.loads(r["definition"])} for r in rows]

    @app.post("/api/workspaces/{wid}/routines")
    async def create(wid: str, request: Request):
        uid = app.state.runtime.workspaces.user(request).id
        app.state.runtime.workspaces.role(uid, wid, owner=True)
        definition = await body(request, RoutineDefinition)
        service.authorize(uid, wid, definition)
        rid = identifier("routine")
        upcoming = next_time(definition, datetime.now(UTC))
        with service.store.transaction() as db:
            if (
                db.execute(
                    "SELECT COUNT(*) FROM routines WHERE workspace_id=? AND deleted=0",
                    (wid,),
                ).fetchone()[0]
                >= 100
            ):
                raise Conflict("Workspace routine limit reached (100 routines).")
            cursor = db.execute(
                "SELECT COALESCE(MAX(seq),0) FROM bot_events WHERE bot_id=?",
                (definition.bot_id,),
            ).fetchone()[0]
            db.execute(
                "INSERT INTO routines VALUES (?,?,?,1,?,?,NULL,?,0)",
                (
                    rid,
                    wid,
                    uid,
                    int(definition.enabled),
                    upcoming.isoformat() if upcoming else None,
                    cursor,
                ),
            )
            db.execute(
                "INSERT INTO routine_versions VALUES (?,1,?,?)",
                (rid, packed(definition.model_dump()), stamp()),
            )
            if definition.bot_id:
                db.execute(
                    "INSERT INTO search_index VALUES (?,?,'routine',?,?)",
                    (rid, definition.bot_id, definition.name, definition.prompt),
                )
        return {"id": rid, "version": 1, "next_at": upcoming}

    @app.patch("/api/routines/{rid}")
    async def update(rid: str, request: Request):
        uid = app.state.runtime.workspaces.user(request).id
        routine = service.get(uid, rid, True)
        definition = await body(request, RoutineDefinition)
        service.authorize(uid, routine["workspace_id"], definition)
        if routine["version"] != definition.version:
            raise Conflict("Routine changed in another tab.")
        upcoming = next_time(definition, datetime.now(UTC))
        with service.store.transaction() as db:
            changed = db.execute(
                "UPDATE routines SET version=version+1,enabled=?,next_at=?,principal_id=? WHERE id=? AND version=?",
                (
                    int(definition.enabled),
                    upcoming.isoformat() if upcoming else None,
                    uid,
                    rid,
                    definition.version,
                ),
            ).rowcount
            if not changed:
                raise Conflict("Routine changed in another tab.")
            db.execute(
                "INSERT INTO routine_versions VALUES (?,?,?,?)",
                (rid, definition.version + 1, packed(definition.model_dump()), stamp()),
            )
            db.execute(
                "DELETE FROM search_index WHERE resource_id=? AND kind='routine'",
                (rid,),
            )
            if definition.bot_id:
                db.execute(
                    "INSERT INTO search_index VALUES (?,?,'routine',?,?)",
                    (rid, definition.bot_id, definition.name, definition.prompt),
                )
        return {"id": rid, "version": definition.version + 1}

    @app.delete("/api/routines/{rid}")
    async def remove(rid: str, request: Request):
        service.get(app.state.runtime.workspaces.user(request).id, rid, True)
        with service.store.transaction() as db:
            db.execute(
                "UPDATE routines SET enabled=0,deleted=1,webhook_secret=NULL WHERE id=?",
                (rid,),
            )
            db.execute(
                "DELETE FROM search_index WHERE resource_id=? AND kind='routine'",
                (rid,),
            )
        return {"status": "deleted"}

    @app.post("/api/routines/{rid}/run")
    async def run(rid: str, request: Request):
        routine = service.get(app.state.runtime.workspaces.user(request).id, rid, True)
        command = await body(request, Command)
        return service.claim(routine, "manual:" + command.request_id)

    @app.get("/api/routines/{rid}/history")
    async def history(rid: str, request: Request, before: str = "9999"):
        service.get(app.state.runtime.workspaces.user(request).id, rid)
        with service.store.transaction() as db:
            return [
                dict(r)
                for r in db.execute(
                    "SELECT * FROM routine_jobs WHERE routine_id=? AND created_at<? ORDER BY created_at DESC LIMIT 100",
                    (rid, before),
                )
            ]

    @app.post("/api/routines/preview")
    async def preview(request: Request):
        app.state.runtime.workspaces.user(request)
        definition = await body(request, RoutineDefinition)
        after, times = datetime.now(UTC), []
        for _ in range(5):
            after = next_time(definition, after)
            if not after:
                break
            times.append(after.isoformat())
        return {
            "times": times,
            "dst": "Skip nonexistent local times; use the first occurrence of repeated times.",
            "missed": definition.missed,
        }

    @app.post("/api/routines/{rid}/webhook-secret")
    async def rotate(rid: str, request: Request):
        routine = service.get(app.state.runtime.workspaces.user(request).id, rid, True)
        if json.loads(routine["definition"])["trigger"] != "webhook":
            raise Conflict("Routine is not a webhook routine.")
        secret = secrets.token_urlsafe(32)
        with service.store.transaction() as db:
            db.execute(
                "UPDATE routines SET webhook_secret=? WHERE id=?",
                (
                    app.state.runtime.catalog.seal(secret.encode()),
                    rid,
                ),
            )
        return {
            "secret": secret,
            "path": f"/api/webhooks/{rid}",
            "signature": "HMAC-SHA256(timestamp + '.' + delivery_id + '.' + raw_body)",
            "headers": ["X-Agent-Timestamp", "X-Agent-Delivery", "X-Agent-Signature"],
        }

    @app.post("/api/webhooks/{rid}")
    async def webhook(rid: str, request: Request):
        raw = await request.body()
        if len(raw) > 65536:
            raise HTTPException(413, "Webhook exceeds 64 KiB.")
        timestamp, delivery, signature = (
            request.headers.get(k, "")
            for k in ("x-agent-timestamp", "x-agent-delivery", "x-agent-signature")
        )
        if (
            not timestamp.isdigit()
            or abs(time.time() - int(timestamp)) > 300
            or not re.fullmatch(r"[A-Za-z0-9_-]{8,128}", delivery)
        ):
            raise HTTPException(401, "Invalid webhook timestamp or delivery ID.")
        with service.store.transaction() as db:
            routine = db.execute(
                "SELECT r.*,v.definition FROM routines r JOIN routine_versions v ON v.routine_id=r.id AND v.version=r.version WHERE r.id=? AND r.enabled=1 AND r.deleted=0",
                (rid,),
            ).fetchone()
        if (
            not routine
            or not routine["webhook_secret"]
            or json.loads(routine["definition"])["trigger"] != "webhook"
        ):
            raise HTTPException(404, "Webhook unavailable.")
        secret = app.state.runtime.catalog.unseal(routine["webhook_secret"])
        expected = hmac.new(
            secret,
            timestamp.encode() + b"." + delivery.encode() + b"." + raw,
            hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(expected, signature):
            raise HTTPException(401, "Invalid webhook signature.")
        try:
            value = json.loads(raw)
            if (
                not isinstance(value, dict)
                or set(value) != {"data"}
                or not isinstance(value["data"], dict)
                or len(packed(value)) > 16000
            ):
                raise ValueError()
        except ValueError:
            raise HTTPException(422, "Webhook requires a data object of at most 16,000 characters.")
        digest = hashlib.sha256(raw).hexdigest()
        with service.store.transaction() as db:
            old = db.execute(
                "SELECT digest FROM webhook_deliveries WHERE routine_id=? AND delivery_id=?",
                (rid, delivery),
            ).fetchone()
            if old and old[0] != digest:
                raise Conflict("Delivery ID reused with another body.")
            if old:
                existing = db.execute(
                    "SELECT * FROM routine_jobs WHERE routine_id=? AND occurrence=? ORDER BY created_at LIMIT 1",
                    (rid, "webhook:" + delivery),
                ).fetchone()
                if existing:
                    return dict(existing)
            db.execute(
                "INSERT OR IGNORE INTO webhook_deliveries VALUES (?,?,?,?)",
                (rid, delivery, digest, stamp()),
            )
        return service.claim(routine, "webhook:" + delivery, value["data"])
