from __future__ import annotations

import secrets

from fastapi import HTTPException, Request, WebSocket
from fastapi.responses import JSONResponse
from starlette.exceptions import WebSocketException

from agentbot_control.app import (
    _UNSAFE_METHODS,
    _bot_json,
    _credential_json,
    _json,
    _owned_bot,
    _require_user,
    _with_cookie,
)
from agentbot_control.auth import COOKIE_NAME
from agentbot_control.authentication import AuthenticationLimited
from agentbot_control.store import (
    CatalogConflict,
    CatalogError,
)
from agentbot_control.transport import serve_legacy


def register_http(app, coordinator, persistence_probe):
    @app.middleware("http")
    async def guard_origin(request: Request, call_next):
        if request.method in _UNSAFE_METHODS:
            origin = request.headers.get("origin")
            if origin is not None and origin not in app.state.cors_origins:
                return JSONResponse({"detail": "Origin is not allowed."}, status_code=403)
        return await call_next(request)

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/ready")
    async def ready() -> JSONResponse:
        healthy = coordinator.accepting and coordinator.store.health.ready()
        if healthy:
            healthy = await persistence_probe.healthy()
        return JSONResponse(
            {"status": "ready" if healthy else "unavailable"}, status_code=200 if healthy else 503
        )

    @app.exception_handler(AuthenticationLimited)
    async def authentication_limited(_request, exc):
        return JSONResponse(
            {"detail": str(exc)}, status_code=429, headers={"Retry-After": str(exc.retry_after)}
        )

    @app.post("/api/register")
    async def register(request: Request) -> JSONResponse:
        if not app.state.allow_register:
            raise HTTPException(status_code=403, detail="Registration is closed.")
        body = await _json(request)
        try:
            user, token = await app.state.authentication.execute(
                "register",
                str(body.get("username", "")),
                str(body.get("password", "")),
                request.client.host if request.client else "unknown",
            )
        except CatalogError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        await coordinator.store.offload(lambda: coordinator.store.workspace(user.id))
        return _with_cookie(user, token, app.state.cookie_secure, app.state.cookie_samesite)

    @app.post("/api/login")
    async def login(request: Request) -> JSONResponse:
        body = await _json(request)
        try:
            user, token = await app.state.authentication.execute(
                "login",
                str(body.get("username", "")),
                str(body.get("password", "")),
                request.client.host if request.client else "unknown",
            )
        except CatalogError as exc:
            raise HTTPException(status_code=401, detail=str(exc)) from exc
        return _with_cookie(user, token, app.state.cookie_secure, app.state.cookie_samesite)

    @app.post("/api/logout")
    async def logout(request: Request) -> JSONResponse:
        app.state.catalog.logout(request.cookies.get(COOKIE_NAME))
        response = JSONResponse({"status": "ok"})
        response.delete_cookie(
            COOKIE_NAME,
            path="/",
            secure=app.state.cookie_secure,
            httponly=True,
            samesite=app.state.cookie_samesite,
        )
        return response

    @app.get("/api/me")
    async def me(request: Request) -> dict[str, str]:
        user = _require_user(request, app.state.catalog)
        return {"id": user.id, "username": user.username}

    @app.get("/api/credentials")
    async def list_credentials(request: Request) -> list[dict[str, str]]:
        user = _require_user(request, app.state.catalog)
        return [_credential_json(item) for item in app.state.catalog.list_credentials(user.id)]

    @app.post("/api/credentials")
    async def create_credential(request: Request) -> JSONResponse:
        user = _require_user(request, app.state.catalog)
        body = await _json(request)
        try:
            credential = app.state.catalog.create_credential(
                user.id,
                str(body.get("provider", "")),
                str(body.get("label", "")),
                str(body.get("api_key", "")),
                str(body.get("endpoint", "")),
            )
        except CatalogError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return JSONResponse(_credential_json(credential), status_code=201)

    @app.patch("/api/credentials/{credential_id}")
    async def update_credential(credential_id: str, request: Request) -> dict[str, str]:
        user = _require_user(request, app.state.catalog)
        body = await _json(request)
        if "provider" in body:
            raise HTTPException(status_code=400, detail="Provider cannot change after create.")
        if not any(key in body for key in ("label", "endpoint", "api_key")):
            raise HTTPException(
                status_code=400, detail="Send a label, endpoint, or api_key to update."
            )
        try:
            credential = app.state.catalog.update_credential(
                user.id,
                credential_id,
                label=str(body["label"]) if "label" in body else None,
                endpoint=str(body["endpoint"]) if "endpoint" in body else None,
                api_key=str(body["api_key"]) if "api_key" in body else None,
            )
        except CatalogError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if credential is None:
            raise HTTPException(status_code=404, detail="API key not found.")
        return _credential_json(credential)

    @app.delete("/api/credentials/{credential_id}")
    async def delete_credential(credential_id: str, request: Request) -> dict[str, str]:
        user = _require_user(request, app.state.catalog)
        try:
            deleted = app.state.catalog.delete_credential(user.id, credential_id)
        except CatalogConflict as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        if not deleted:
            raise HTTPException(status_code=404, detail="API key not found.")
        return {"status": "deleted", "id": credential_id}

    @app.get("/api/bots")
    async def list_bots(request: Request) -> list[dict[str, object]]:
        user = _require_user(request, app.state.catalog)
        import json

        with coordinator.store.transaction() as db:
            pref = db.execute(
                "SELECT data FROM user_preferences WHERE user_id=?", (user.id,)
            ).fetchone()
        wid = request.query_params.get("workspace_id") or (
            json.loads(pref[0]).get("workspace_id") if pref else None
        )
        return [
            {**_bot_json(bot), **coordinator.tools.state(bot.id)}
            for bot in coordinator.workspaces.list_bots(user.id, wid)
        ]

    @app.post("/api/bots")
    async def create_bot(request: Request) -> JSONResponse:
        user = _require_user(request, app.state.catalog)
        body = await _json(request)
        framework = str(body.get("framework", "")).lower()
        import json

        with coordinator.store.transaction() as db:
            pref = db.execute(
                "SELECT data FROM user_preferences WHERE user_id=?", (user.id,)
            ).fetchone()
        wid = body.get("workspace_id") or (
            json.loads(pref[0]).get("workspace_id") if pref else None
        )
        if wid:
            coordinator.workspaces.role(user.id, str(wid), owner=True)
        if not app.state.kernel.registry.known(framework):
            raise HTTPException(status_code=400, detail=f"Unknown framework '{framework}'.")
        from agentbot.tools import legacy_selection
        from agentbot_tools.registry import REGISTRY

        try:
            with coordinator.store.transaction() as db:
                selection = coordinator.tools.validate(
                    db,
                    None,
                    framework,
                    body.get("tool_selection", legacy_selection(framework, REGISTRY)),
                )
                bot = app.state.catalog.create_bot(
                    user.id,
                    str(body.get("name", "")),
                    framework,
                    str(body.get("instructions", "")),
                    str(body.get("credential_id", "")),
                    str(body.get("model", "")),
                    default_prompt=body.get("default_prompt", ""),
                    _db=db,
                )
                personal_wid = coordinator.store._workspace(db, user.id)
                db.execute(
                    "INSERT INTO bot_streams(bot_id,workspace_id) VALUES (?,?)",
                    (bot.id, wid or personal_wid),
                )
                coordinator.tools.replace(db, bot.id, selection, user.id, provenance="creation")
                if (
                    "join_workspace_channel" in body
                    and type(body["join_workspace_channel"]) is not bool
                ):
                    raise HTTPException(422, "join_workspace_channel must be a boolean.")
                join = body.get("join_workspace_channel")
                if join and not any(
                    item["library_id"] == "workspace.messaging" for item in selection
                ):
                    raise HTTPException(
                        422, "Select the Bot channel bundle to join the workspace channel."
                    )
                coordinator.channels.creation(db, bot, join)
        except CatalogError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return JSONResponse({**_bot_json(bot), **coordinator.tools.state(bot.id)}, status_code=201)

    @app.get("/api/bots/{bot_id}")
    async def get_bot(bot_id: str, request: Request) -> dict[str, object]:
        user = _require_user(request, app.state.catalog)
        bot = coordinator.workspaces.bot(user.id, bot_id)
        coordinator.ensure(bot)
        messages = [
            {"role": m["role"], "content": m["content"]}
            for m in coordinator.store.messages(bot.id)["messages"]
        ]
        return {**_bot_json(bot), **coordinator.tools.state(bot.id), "messages": messages}

    @app.patch("/api/bots/{bot_id}")
    async def update_bot(bot_id: str, request: Request) -> dict[str, object]:
        user = _require_user(request, app.state.catalog)
        body = await _json(request)
        if not any(
            key in body
            for key in (
                "name",
                "instructions",
                "credential_id",
                "model",
                "default_prompt",
                "tool_selection",
                "collaboration",
            )
        ):
            raise HTTPException(
                status_code=400,
                detail="Send a name, instructions, credential_id, model, or default_prompt to update.",
            )
        if "framework" in body:
            raise HTTPException(status_code=400, detail="Framework cannot change after create.")
        changes: dict[str, str] = {}
        if "name" in body:
            changes["name"] = str(body["name"])
        if "instructions" in body:
            changes["instructions"] = str(body["instructions"])
        if "credential_id" in body:
            changes["credential_id"] = str(body["credential_id"])
        if "model" in body:
            changes["model"] = str(body["model"])
        if "default_prompt" in body:
            changes["default_prompt"] = body["default_prompt"]
        current = _owned_bot(app.state.catalog, user, bot_id)
        coordinator.ensure(current)
        if "tool_selection" in body and type(body.get("expected_tools_revision")) is not int:
            raise HTTPException(422, "expected_tools_revision is required when updating tools.")
        try:
            with coordinator.store.transaction() as db:
                collaboration = None
                if "collaboration" in body:
                    from pydantic import ValidationError

                    from agentbot_control.channels import Participation

                    try:
                        collaboration = Participation.model_validate(body["collaboration"])
                    except ValidationError as exc:
                        raise HTTPException(422, "Invalid collaboration settings.") from exc
                    entry = db.execute(
                        "SELECT revision FROM workspace_bot_directory WHERE bot_id=?", (bot_id,)
                    ).fetchone()
                    if not entry or entry[0] != collaboration.revision:
                        raise HTTPException(
                            409, "Collaboration settings changed. Reload and review your draft."
                        )
                if "tool_selection" in body:
                    selection = coordinator.tools.validate(
                        db, bot_id, current.framework, body["tool_selection"]
                    )
                    coordinator.tools.replace(
                        db, bot_id, selection, user.id, body["expected_tools_revision"]
                    )
                bot = app.state.catalog.update_bot(user.id, bot_id, _db=db, **changes)
                coordinator.channels.sync_bot(db, bot)
                if collaboration is not None:
                    revision = db.execute(
                        "SELECT revision FROM workspace_bot_directory WHERE bot_id=?", (bot_id,)
                    ).fetchone()[0]
                    coordinator.channels.enroll(
                        db, bot_id, user.id, collaboration.model_copy(update={"revision": revision})
                    )
        except CatalogError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        coordinator.tools.wake(bot_id)
        return {**_bot_json(bot), **coordinator.tools.state(bot_id)}

    @app.delete("/api/bots/{bot_id}")
    async def delete_bot(bot_id: str, request: Request) -> dict[str, str]:
        user = _require_user(request, app.state.catalog)
        bot = _owned_bot(app.state.catalog, user, bot_id)
        coordinator.ensure(bot)
        from agentbot_control.shared_computers.removal import remove_idle_bot

        with coordinator.store.transaction() as db:
            shared_deleted = remove_idle_bot(db, bot, app.state.catalog, coordinator.channels)
            if not shared_deleted:
                coordinator.channels.retire(db, bot.id)
        if shared_deleted:
            app.state.kernel.sessions.delete(bot.id)
            return {"status": "deleted", "id": bot.id}
        result = await coordinator.close(bot.id, "delete_" + secrets.token_hex(16), actor=user)
        if result.get("status") == "accepted":
            raise HTTPException(
                409,
                "Cloud retirement is in progress. Wait for it to complete, then delete the bot. Azure inventory will be retained.",
            )
        app.state.kernel.sessions.delete(bot.id)
        with coordinator.store.transaction() as db:
            coordinator.channels.retire(db, bot.id, final=True)
            app.state.catalog.delete_bot(user.id, bot.id, _db=db)
        return {"status": "deleted", "id": bot.id}

    @app.websocket("/ws")
    async def websocket_endpoint(websocket: WebSocket) -> None:
        origin = websocket.headers.get("origin")
        if origin is not None and origin not in app.state.cors_origins:
            raise WebSocketException(code=1008)
        await websocket.accept()
        user = app.state.catalog.user_from_token(websocket.cookies.get(COOKIE_NAME))
        if user is None:
            await websocket.send_json({"event": "error", "payload": "Sign in required."})
            await websocket.close()
            return
        await serve_legacy(websocket, coordinator, user)
