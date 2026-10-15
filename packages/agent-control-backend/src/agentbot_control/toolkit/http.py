from __future__ import annotations

import asyncio
import re
from typing import Literal

import httpx
from fastapi import Request

from agentbot_control.auth import COOKIE_NAME
from agentbot_control.authorization import request_bot
from agentbot_control.event_store import identifier, packed, sanitized, stamp
from agentbot_control.schemas import Conflict
from agentbot_control.toolkit import (
    ConnectionDefinition,
    ConnectorCall,
    RecordingCommand,
    Replay,
    SkillDefinition,
)
from agentbot_control.transport import body


def register_toolkit_routes(app):
    service = app.state.runtime.toolkit

    @app.get("/api/toolkit/catalog")
    async def catalog(request: Request):
        app.state.runtime.workspaces.user(request)
        return [
            {
                "id": "github",
                "version": 1,
                "name": "GitHub repository issues",
                "auth_mode": "fine_grained_pat",
                "scopes": [
                    "Repository metadata: read",
                    "Repository issues: read/write",
                ],
                "tools": ["list_issues", "create_issue"],
                "endpoint": "https://api.github.com",
            }
        ]

    @app.get("/api/bots/{bot_id}/toolkit")
    async def listing(bot_id: str, request: Request):
        request_bot(request, bot_id)
        with service.store.transaction() as db:
            skills = [
                dict(r)
                for r in db.execute(
                    "SELECT s.*,EXISTS(SELECT 1 FROM bot_tool_bindings i WHERE i.bot_id=? AND i.library_id='skills.replay' AND i.enabled=1 AND json_extract(i.configuration,'$.resource_id')=s.id) AS installed FROM skill_versions s JOIN bot_streams b ON b.bot_id=s.bot_id WHERE b.workspace_id=(SELECT workspace_id FROM bot_streams WHERE bot_id=?) ORDER BY created_at DESC LIMIT 100",
                    (bot_id, bot_id),
                )
            ]
            connections = [
                dict(r)
                for r in db.execute(
                    "SELECT id,provider,repository,status,version,checked_at FROM connections WHERE bot_id=?",
                    (bot_id,),
                )
            ]
            recordings = [
                dict(r)
                for r in db.execute(
                    "SELECT id,state,private,steps,created_at FROM recordings WHERE bot_id=? ORDER BY created_at DESC LIMIT 20",
                    (bot_id,),
                )
            ]
        return {"skills": skills, "connections": connections, "recordings": recordings}

    @app.post("/api/bots/{bot_id}/sessions/{sid}/recordings")
    async def recording(bot_id: str, sid: str, request: Request):
        user, _ = request_bot(request, bot_id)
        command = await body(request, RecordingCommand)
        async with app.state.runtime.control.locks.setdefault(command.lease_id, asyncio.Lock()):
            app.state.runtime.control.check(
                bot_id,
                sid,
                user,
                request.cookies[COOKIE_NAME],
                command.lease_id,
                command.client_id,
                command.fence,
            )
            old = service.recording(command.lease_id)
            with service.store.transaction() as db:
                if command.operation == "start" and not old:
                    rid = identifier("recording")
                    db.execute(
                        "INSERT INTO recordings VALUES (?,?,?,?,'recording',0,'[]',?)",
                        (rid, bot_id, user.id, command.lease_id, stamp()),
                    )
                elif old:
                    rid = old["id"]
                    if command.operation in {"private", "public"}:
                        db.execute(
                            "UPDATE recordings SET private=? WHERE id=?",
                            (int(command.operation == "private"), rid),
                        )
                    else:
                        state = {
                            "pause": "paused",
                            "resume": "recording",
                            "stop": "stopped",
                            "start": old["state"],
                        }[command.operation]
                        db.execute("UPDATE recordings SET state=? WHERE id=?", (state, rid))
                else:
                    raise Conflict("No active recording.")
                service.store._event(
                    db,
                    bot_id,
                    "recording.changed",
                    {
                        "recording_id": rid,
                        "operation": command.operation,
                        "actor": user.id,
                    },
                )
            return {"id": rid, "operation": command.operation}

    @app.post("/api/bots/{bot_id}/skills")
    async def save(bot_id: str, request: Request):
        user, _ = request_bot(request, bot_id)
        app.state.runtime.workspaces.bot(user.id, bot_id, "owner")
        command = await body(request, SkillDefinition)
        with service.store.transaction() as db:
            recording = db.execute(
                "SELECT * FROM recordings WHERE id=? AND bot_id=? AND user_id=? AND state='stopped'",
                (command.recording_id, bot_id, user.id),
            ).fetchone()
        if not recording:
            raise Conflict("Stop an owned recording before reviewing and saving a skill.")
        if any(not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,39}", key) for key in command.parameters):
            raise Conflict("Invalid parameter name.")
        for step in command.steps:
            if len(packed(step)) > 4096 or step.get("operation") not in {
                "input",
                "open_browser",
                "click_element",
                "checkpoint",
            }:
                raise Conflict("Unsupported step: use an explicit manual checkpoint.")
            if step["operation"] == "input" and (
                step.get("surface") not in {"browser", "desktop"}
                or not isinstance(step.get("input"), dict)
                or not all(
                    isinstance(step.get(k), int) and 0 < step[k] <= 4096
                    for k in ("width", "height")
                )
            ):
                raise Conflict("Input steps require surface and viewport checks.")
            if step["operation"] == "open_browser" and not str(step.get("url", "")).startswith(
                ("https://", "http://")
            ):
                raise Conflict("Browser steps require an HTTP(S) URL.")
            if step["operation"] == "click_element" and not step.get("selector"):
                raise Conflict("Selector required.")
            if set(re.findall(r"\{\{([A-Za-z][A-Za-z0-9_]*)\}\}", packed(step))) - set(
                command.parameters
            ):
                raise Conflict("Unknown skill parameter.")
        sid = identifier("skill")
        with service.store.transaction() as db:
            db.execute(
                "INSERT INTO skill_versions VALUES (?,?,?,?,?,?,?)",
                (
                    sid,
                    bot_id,
                    command.name,
                    command.description,
                    packed(command.parameters),
                    packed(sanitized(command.steps)),
                    stamp(),
                ),
            )
            db.execute("INSERT INTO installations VALUES (?,'skill',?)", (bot_id, sid))
            app.state.runtime.tools.resource_selection(db, bot_id, "skill", sid, True)
            db.execute(
                "INSERT INTO search_index VALUES (?,?,'skill',?,?)",
                (sid, bot_id, command.name, command.description),
            )
        return {"id": sid, "installed": True, "immutable": True}

    @app.post("/api/bots/{bot_id}/skills/{skill_id}/replay")
    async def replay(bot_id: str, skill_id: str, request: Request):
        user, bot = request_bot(request, bot_id)
        command = await body(request, Replay)
        program = service.program(user.id, bot_id, skill_id, command.parameters)
        return await app.state.runtime.start(
            user,
            bot,
            command.request_id,
            "Replay skill " + skill_id + " " + packed(command.parameters),
            "skill",
            program=program,
            resume_sid=(service.store.computer(bot_id) or {}).get("id")
            if command.resume_paused
            else None,
        )

    @app.post("/api/bots/{bot_id}/connections/github")
    async def connect(bot_id: str, request: Request):
        user = app.state.runtime.workspaces.user(request)
        app.state.runtime.workspaces.bot(user.id, bot_id, "owner")
        command = await body(request, ConnectionDefinition)
        cid = identifier("connection")
        secret = app.state.runtime.catalog.seal(command.token.encode())
        with service.store.transaction() as db:
            db.execute(
                "INSERT INTO connections VALUES (?,?,?,'github',?,?,1,'needs_auth',NULL)",
                (cid, bot_id, user.id, command.repository, secret),
            )
            db.execute("INSERT INTO installations VALUES (?,'connector',?)", (bot_id, cid))
            app.state.runtime.tools.resource_selection(db, bot_id, "connector", cid, True)
        try:
            result = await service.checked_github(bot_id, cid, "health", {})
        except Conflict:
            result = {"status": service.connection(bot_id, cid)["status"]}
        return {"id": cid, **result}

    @app.post("/api/bots/{bot_id}/connections/{cid}/health")
    async def health(bot_id: str, cid: str, request: Request):
        request_bot(request, bot_id)
        return await service.checked_github(bot_id, cid, "health", {})

    @app.post("/api/bots/{bot_id}/connections/{cid}/rotate")
    async def rotate(bot_id: str, cid: str, request: Request):
        user = app.state.runtime.workspaces.user(request)
        app.state.runtime.workspaces.bot(user.id, bot_id, "owner")
        command = await body(request, ConnectionDefinition)
        async with service.connection_locks.setdefault(cid, asyncio.Lock()):
            service.connection(bot_id, cid)
            with service.store.transaction() as db:
                db.execute(
                    "UPDATE connections SET secret=?,repository=?,version=version+1,status='needs_auth',checked_at=NULL WHERE id=? AND bot_id=?",
                    (
                        app.state.runtime.catalog.seal(command.token.encode()),
                        command.repository,
                        cid,
                        bot_id,
                    ),
                )
        try:
            return await service.checked_github(bot_id, cid, "health", {})
        except (Conflict, httpx.HTTPError):
            return {"status": service.connection(bot_id, cid)["status"]}

    @app.post("/api/bots/{bot_id}/toolkit/skill/{skill_id}")
    async def install_skill(bot_id: str, skill_id: str, request: Request):
        user = app.state.runtime.workspaces.user(request)
        app.state.runtime.workspaces.bot(user.id, bot_id, "owner")
        with service.store.transaction() as db:
            skill = db.execute(
                "SELECT s.id FROM skill_versions s JOIN bot_streams b ON b.bot_id=s.bot_id WHERE s.id=? AND b.workspace_id=(SELECT workspace_id FROM bot_streams WHERE bot_id=?)",
                (skill_id, bot_id),
            ).fetchone()
            if not skill:
                raise Conflict("Skill version is unavailable in this workspace.")
            db.execute(
                "INSERT OR IGNORE INTO installations VALUES (?,'skill',?)",
                (bot_id, skill_id),
            )
            app.state.runtime.tools.resource_selection(db, bot_id, "skill", skill_id, True)
        return {"status": "installed", "id": skill_id}

    @app.post("/api/bots/{bot_id}/connections/{cid}/invoke")
    async def invoke(bot_id: str, cid: str, request: Request):
        user, bot = request_bot(request, bot_id)
        command = await body(request, ConnectorCall)
        program = service.connector_program(bot_id, cid, command)
        return await app.state.runtime.start(
            user,
            bot,
            command.request_id,
            "GitHub " + cid + " " + command.operation + " " + command.title + " " + command.text,
            "connector",
            program=program,
        )

    @app.delete("/api/bots/{bot_id}/toolkit/{kind}/{resource_id}")
    async def uninstall(
        bot_id: str,
        kind: Literal["skill", "connector"],
        resource_id: str,
        request: Request,
    ):
        app.state.runtime.workspaces.bot(
            app.state.runtime.workspaces.user(request).id, bot_id, "owner"
        )
        async with service.connection_locks.setdefault(resource_id, asyncio.Lock()):
            with service.store.transaction() as db:
                db.execute(
                    "DELETE FROM installations WHERE bot_id=? AND kind=? AND resource_id=?",
                    (bot_id, kind, resource_id),
                )
                if kind == "connector":
                    db.execute(
                        "UPDATE connections SET status='revoked',secret=NULL,version=version+1 WHERE id=? AND bot_id=?",
                        (resource_id, bot_id),
                    )
                app.state.runtime.tools.resource_selection(db, bot_id, kind, resource_id, False)
        app.state.runtime.tools.wake(bot_id)
        return {"status": "uninstalled", "credential": "revoked_locally"}
