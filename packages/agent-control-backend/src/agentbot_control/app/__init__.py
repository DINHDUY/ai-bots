"""FastAPI control plane: accounts, owned bots, and authenticated chat."""

from __future__ import annotations

import asyncio
import logging
import os
import secrets
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from agentbot.bootstrap import build_kernel
from agentbot.kernel import EngineRuntimeManager
from fastapi import FastAPI, HTTPException, Request, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import WebSocketException

from agentbot_control.auth import COOKIE_NAME
from agentbot_control.authentication import Authentication, AuthenticationLimited
from agentbot_control.store import (
    Bot,
    Catalog,
    CatalogConflict,
    CatalogError,
    Credential,
    User,
)
from agentbot_control.supervision import PersistenceProbe
from agentbot_control.transport import register_routes, serve_legacy

logger = logging.getLogger("AgentBotControl")
_UNSAFE_METHODS = frozenset({"POST", "PATCH", "DELETE"})
_SAMESITE = frozenset({"lax", "strict", "none"})


def create_app(
    kernel: EngineRuntimeManager | None = None,
    *,
    secret: str | None = None,
    control_db: Path | None = None,
    allow_register: bool | None = None,
    cookie_secure: bool | None = None,
    cors_origins: list[str] | None = None,
    cookie_samesite: str | None = None,
) -> FastAPI:
    signing_secret = secret if secret is not None else os.environ.get("AGENTBOT_SECRET", "")
    if not signing_secret:
        raise RuntimeError("AGENTBOT_SECRET is required.")
    database = control_db or Path(os.environ.get("CONTROL_DB", "data/control.sqlite"))
    if database.with_suffix(".restore-only").exists():
        raise RuntimeError(
            "Verification restore is fenced; review deployment and provider identities before activation."
        )
    runtime = kernel or build_kernel(control=True)
    catalog = Catalog(database, signing_secret)
    register_open = _allow_register() if allow_register is None else allow_register
    secure_cookie = _cookie_secure() if cookie_secure is None else cookie_secure
    origins = _cors_origins() if cors_origins is None else _checked_origins(cors_origins)
    samesite = (
        _cookie_samesite(secure_cookie)
        if cookie_samesite is None
        else _checked_samesite(cookie_samesite, secure_cookie)
    )
    idle_seconds = float(os.environ.get("SESSION_IDLE_SECONDS", "900"))
    approval_timeout = float(os.environ.get("APPROVAL_TIMEOUT_SECONDS", "120"))

    from agentbot_control.composition import build_services

    services = build_services(
        runtime,
        catalog,
        database,
        approval_timeout=approval_timeout,
        run_timeout=float(os.environ.get("RUN_TIMEOUT_SECONDS", "900")),
        retention_days=int(os.environ.get("EVENT_RETENTION_DAYS", "30")),
        blob_limit=int(os.environ.get("WORKSPACE_BLOB_LIMIT_BYTES", str(256 * 1024 * 1024))),
    )
    coordinator = services.runs
    persistence_probe = PersistenceProbe(
        lambda: catalog.db.read(lambda db: db.execute("SELECT 1").fetchone())
    )

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        if coordinator.users:
            await coordinator.startup()
            try:
                yield
            finally:
                await coordinator.shutdown()
            return
        authentication = Authentication(catalog)
        _app.state.authentication = authentication
        health = coordinator.store.health
        started = False
        try:
            await coordinator.startup()
            started = True
            health.start("capture_cleanup", coordinator.store.captures.loop(), timeout=180)
            health.start("run_cleanup", coordinator.sweep(idle_seconds), timeout=60)
            health.start("computer_monitor", coordinator.computers.monitor(), timeout=120)
            health.start("control_leases", coordinator.control.sweep(), timeout=15)
            health.start("routines", coordinator.routines.loop(), timeout=30)
            health.start("channels", coordinator.channels.loop(), timeout=30)
            health.start(
                "workspace_cleanup",
                coordinator.workspace_deletions.cleanup.loop(health.progressed),
                timeout=30,
            )
            yield
        finally:
            coordinator.accepting = False
            await health.stop()
            try:
                if started:
                    await coordinator.shutdown()
            finally:
                await persistence_probe.close()
                await asyncio.to_thread(authentication.close)

    app = FastAPI(title="Agent Bot Control Plane", lifespan=lifespan)
    from agentbot_control.request_limits import RequestLimits

    app.add_middleware(RequestLimits)
    app.state.runtime = coordinator
    app.state.services = coordinator.services
    app.state.kernel = runtime
    app.state.catalog = catalog
    app.state.allow_register = register_open
    app.state.cookie_secure = secure_cookie
    app.state.cookie_samesite = samesite
    app.state.cors_origins = set(origins)
    app.state.approval_timeout = approval_timeout
    coordinator.windows.register(app)
    coordinator.cloud.routes(app)

    http.register_http(app, coordinator, persistence_probe)

    from agentbot_control.computer import register_computer_routes
    from agentbot_control.control import register_control_routes
    from agentbot_control.files import register_file_routes
    from agentbot_control.groups import register_group_routes
    from agentbot_control.lifecycle import register_lifecycle_routes
    from agentbot_control.routines import register_routine_routes
    from agentbot_control.shared_computers.http import (
        register_routes as register_shared_computer_routes,
    )
    from agentbot_control.terminals import register_terminal_routes
    from agentbot_control.toolkit import register_toolkit_routes
    from agentbot_control.workspaces import register_workspace_routes

    if coordinator.workspace_features:
        for register_feature in (
            register_computer_routes,
            register_file_routes,
            register_control_routes,
            register_terminal_routes,
            register_lifecycle_routes,
            register_workspace_routes,
            register_shared_computer_routes,
            register_group_routes,
            register_toolkit_routes,
            register_routine_routes,
        ):
            register_feature(app)
    from agentbot_control.tool_libraries import register_tool_library_routes

    register_tool_library_routes(app)
    from agentbot_control.channels import register_channel_routes

    register_channel_routes(app)
    from agentbot_control.workflow_imports.http import register_routes as register_import_routes

    register_import_routes(app)
    from agentbot_control.workspace_deletions.http import (
        register_routes as register_deletion_routes,
    )

    register_deletion_routes(app)
    register_routes(app)
    from agentbot_control.autopilot import register_autopilot_routes

    register_autopilot_routes(app)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "DELETE"],
        allow_headers=["Content-Type"],
    )
    return app


def main() -> None:
    import uvicorn

    env_path = Path.cwd() / ".env"
    ensure_secret(env_path, Path.cwd() / ".env.example")
    load_dotenv(env_path)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    uvicorn.run(
        "agentbot_control.app:create_app",
        host=os.environ.get("HOST", "127.0.0.1"),
        port=int(os.environ.get("PORT", "8000")),
        factory=True,
    )


async def _json(request: Request) -> dict:
    content_type = request.headers.get("content-type", "")
    media = content_type.split(";", 1)[0].strip().lower()
    if media != "application/json":
        raise HTTPException(status_code=415, detail="Content-Type must be application/json.")
    body = await request.json()
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="JSON object required.")
    return body


def _require_user(request: Request, catalog: Catalog) -> User:
    user = catalog.user_from_token(request.cookies.get(COOKIE_NAME))
    if user is None:
        raise HTTPException(status_code=401, detail="Sign in required.")
    return user


def _owned_bot(catalog: Catalog, user: User, bot_id: str) -> Bot:
    bot = catalog.get_bot(user.id, bot_id)
    if bot is None:
        raise HTTPException(status_code=404, detail="Bot not found.")
    return bot


def _bot_json(bot: Bot) -> dict[str, str | None]:
    return {
        "id": bot.id,
        "name": bot.name,
        "framework": bot.framework,
        "instructions": bot.instructions,
        "default_prompt": bot.default_prompt,
        "credential_id": bot.credential_id,
        "model": bot.model,
        "created_at": bot.created_at,
        "updated_at": bot.updated_at,
    }


def _credential_json(credential: Credential) -> dict[str, str]:
    return {
        "id": credential.id,
        "provider": credential.provider,
        "label": credential.label,
        "endpoint": credential.endpoint,
        "key_hint": credential.key_hint,
        "created_at": credential.created_at,
        "updated_at": credential.updated_at,
    }


def _with_cookie(user: User, token: str, secure: bool, samesite: str) -> JSONResponse:
    response = JSONResponse({"id": user.id, "username": user.username})
    response.set_cookie(
        COOKIE_NAME,
        token,
        httponly=True,
        samesite=samesite,
        secure=secure,
        path="/",
        max_age=int(60 * 60 * 24 * 7),
    )
    return response


def load_dotenv(path: Path) -> None:
    """Copy non-empty keys from a dotenv file without replacing existing variables."""

    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and value and key not in os.environ:
            os.environ[key] = value


def ensure_secret(path: Path, example: Path | None = None) -> None:
    """Create .env from the example and fill a blank AGENTBOT_SECRET."""

    if not path.exists():
        if example is not None and example.is_file():
            path.write_text(example.read_text(encoding="utf-8"), encoding="utf-8")
        else:
            path.write_text("AGENTBOT_SECRET=\n", encoding="utf-8")
    text = path.read_text(encoding="utf-8")
    current = _dotenv_value(text, "AGENTBOT_SECRET")
    if current:
        return
    secret = secrets.token_hex(32)
    lines = text.splitlines()
    replaced = False
    updated: list[str] = []
    for line in lines:
        if line.strip().startswith("AGENTBOT_SECRET="):
            updated.append(f"AGENTBOT_SECRET={secret}")
            replaced = True
        else:
            updated.append(line)
    if not replaced:
        if updated and updated[-1] != "":
            updated.append("")
        updated.append(f"AGENTBOT_SECRET={secret}")
    path.write_text("\n".join(updated) + "\n", encoding="utf-8")


def _dotenv_value(text: str, name: str) -> str:
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        if key.strip() == name:
            return value.strip().strip('"').strip("'")
    return ""


def _allow_register() -> bool:
    return os.environ.get("ALLOW_REGISTER", "1") != "0"


def _cookie_secure() -> bool:
    return os.environ.get("COOKIE_SECURE", "") == "1"


def _cors_origins() -> list[str]:
    raw = os.environ.get("CORS_ORIGINS", "")
    return _checked_origins([item.strip() for item in raw.split(",") if item.strip()])


def _checked_origins(origins: list[str]) -> list[str]:
    if "*" in origins:
        raise RuntimeError("CORS_ORIGINS cannot contain '*' when credentials are enabled.")
    return origins


def _cookie_samesite(secure: bool) -> str:
    value = os.environ.get("COOKIE_SAMESITE", "lax").strip().lower() or "lax"
    return _checked_samesite(value, secure)


def _checked_samesite(value: str, secure: bool) -> str:
    if value not in _SAMESITE:
        raise RuntimeError("COOKIE_SAMESITE must be lax, strict, or none.")
    if value == "none" and not secure:
        raise RuntimeError("COOKIE_SAMESITE=none requires COOKIE_SECURE=1.")
    return value


from agentbot_control.app import http

__all__ = [
    "AsyncIterator",
    "Authentication",
    "AuthenticationLimited",
    "Bot",
    "COOKIE_NAME",
    "CORSMiddleware",
    "Catalog",
    "CatalogConflict",
    "CatalogError",
    "Credential",
    "EngineRuntimeManager",
    "FastAPI",
    "HTTPException",
    "JSONResponse",
    "Path",
    "PersistenceProbe",
    "Request",
    "User",
    "WebSocket",
    "WebSocketException",
    "asynccontextmanager",
    "asyncio",
    "build_kernel",
    "create_app",
    "ensure_secret",
    "http",
    "load_dotenv",
    "logger",
    "logging",
    "main",
    "os",
    "register_routes",
    "secrets",
    "serve_legacy",
]
