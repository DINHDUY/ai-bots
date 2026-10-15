"""Lease-bound PTYs with bounded replay and continuous login validation."""

import asyncio
import base64
import json
import time

import anyio
from fastapi import HTTPException, Request, WebSocket
from pydantic import Field

from agentbot_control.auth import COOKIE_NAME
from agentbot_control.authorization import owned, request_bot
from agentbot_control.control import LeaseCommand
from agentbot_control.event_store import identifier, stamp
from agentbot_control.schemas import Conflict
from agentbot_control.transport import body, connected, send_bounded


class OpenTerminal(LeaseCommand):
    rows: int = Field(default=24, ge=2, le=200)
    cols: int = Field(default=80, ge=2, le=400)


class Terminals:
    def __init__(self, store, control, computers, toolkit, kernel, catalog):
        self.store = store
        self.control = control
        self.computers = computers
        self.toolkit = toolkit
        self.kernel = kernel
        self.catalog = catalog
        self.close_locks = {}

    async def open(self, bot_id, sid, user, token, command):
        async with self.control.locks.setdefault(
            command.lease_id, asyncio.Lock()
        ):
            self.control.check(
                bot_id,
                sid,
                user,
                token,
                command.lease_id,
                command.client_id,
                command.fence,
            )
            with self.store.transaction() as db:
                row = db.execute(
                    "SELECT * FROM terminals WHERE lease_id=? AND status='open'",
                    (command.lease_id,),
                ).fetchone()
                count = db.execute(
                    "SELECT COUNT(*) FROM terminals t JOIN bot_streams b ON b.bot_id=t.bot_id WHERE t.status='open' AND b.workspace_id=(SELECT workspace_id FROM bot_streams WHERE bot_id=?)",
                    (bot_id,),
                ).fetchone()[0]
            if row:
                return dict(row)
            if count >= 2:
                raise Conflict("Workspace terminal quota exceeded (2).")
            _, sandbox = await self.computers.existing(bot_id, sid)
            tid = identifier("terminal")
            # Journal the native ID before creation so lease recovery can close
            # a shell even if the RPC response or backend process is lost.
            with self.store.transaction() as db:
                db.execute(
                    "INSERT INTO terminals VALUES (?,?,?,?,?,'open',?)",
                    (tid, bot_id, sid, command.lease_id, tid, stamp()),
                )
            try:
                await sandbox.terminal(
                    "open", id=tid, rows=command.rows, cols=command.cols
                )
            except Exception:
                await self.close_lease(command.lease_id)
                raise
            self.toolkit.checkpoint(
                command.lease_id,
                "Manual terminal activity requires review; terminal input is not recorded.",
            )
            with self.store.transaction() as db:
                self.store._event(
                    db,
                    bot_id,
                    "terminal.opened",
                    {"terminal_id": tid, "actor": user.id},
                )
            return {"id": tid, "status": "open"}

    async def close_lease(self, lease_id):
        async with self.close_locks.setdefault(lease_id, asyncio.Lock()):
            await self._close_lease(lease_id)

    async def _close_lease(self, lease_id):
        with self.store.transaction() as db:
            rows = db.execute(
                "SELECT * FROM terminals WHERE lease_id=? AND status='open'",
                (lease_id,),
            ).fetchall()
        for row in rows:
            computer = self.store.computer(row["bot_id"])
            if (
                computer
                and computer["id"] == row["session_id"]
                and computer["status"] != "closed"
            ):
                report = await self.kernel.sandboxes.inspect(row["session_id"])
                if report["lifecycle"] == "running":
                    sandbox = await self.kernel.sandboxes.existing(
                        row["session_id"]
                    )
                    await sandbox.terminal("close", id=row["native_id"])
            with self.store.transaction() as db:
                db.execute(
                    "UPDATE terminals SET status='closed' WHERE id=?", (row["id"],)
                )
                self.store._event(
                    db, row["bot_id"], "terminal.closed", {"terminal_id": row["id"]}
                )


def register_terminal_routes(app):
    service = app.state.runtime.terminals
    base = "/api/bots/{bot_id}/sessions/{sid}/terminals"

    @app.get(base)
    async def listing(bot_id: str, sid: str, request: Request):
        request_bot(request, bot_id)
        with service.store.transaction() as db:
            return [
                dict(row)
                for row in db.execute(
                    "SELECT id,session_id,lease_id,status,created_at FROM terminals WHERE bot_id=? AND session_id=? ORDER BY created_at DESC LIMIT 100",
                    (bot_id, sid),
                )
            ]

    @app.post(base + "/{tid}/close")
    async def close(bot_id: str, sid: str, tid: str, request: Request):
        user, _ = request_bot(request, bot_id)
        command = await body(request, LeaseCommand)
        async with service.control.locks.setdefault(
            command.lease_id, asyncio.Lock()
        ):
            service.control.check(
                bot_id,
                sid,
                user,
                request.cookies[COOKIE_NAME],
                command.lease_id,
                command.client_id,
                command.fence,
            )
            with service.store.transaction() as db:
                row = db.execute(
                    "SELECT id FROM terminals WHERE id=? AND bot_id=? AND session_id=? AND lease_id=?",
                    (tid, bot_id, sid, command.lease_id),
                ).fetchone()
            if not row:
                raise HTTPException(404, "Terminal unavailable.")
            await service.close_lease(command.lease_id)
        return {"id": tid, "status": "closed"}

    @app.post(base)
    async def create(bot_id: str, sid: str, request: Request):
        user, _ = request_bot(request, bot_id)
        return await service.open(
            bot_id,
            sid,
            user,
            request.cookies[COOKIE_NAME],
            await body(request, OpenTerminal),
        )

    @app.websocket(base + "/{tid}/ws")
    async def terminal(websocket: WebSocket, bot_id: str, sid: str, tid: str):
        token = websocket.cookies.get(COOKIE_NAME)
        try:
            if websocket.headers.get("origin") not in (None, *app.state.cors_origins):
                raise ValueError("Origin denied")
            user, _ = owned(service.catalog, token, bot_id)
            client, fence = (
                websocket.query_params["client_id"],
                int(websocket.query_params["fence"]),
            )
            with service.store.transaction() as db:
                row = db.execute(
                    "SELECT * FROM terminals WHERE id=? AND bot_id=? AND session_id=? AND status='open'",
                    (tid, bot_id, sid),
                ).fetchone()
            if not row:
                raise ValueError("Terminal unavailable")

            def check():
                owned(service.catalog, token, bot_id)
                service.control.check(
                    bot_id, sid, user, token, row["lease_id"], client, fence
                )

            check()
            _, sandbox = await service.computers.existing(bot_id, sid)
            offset = max(0, int(websocket.query_params.get("offset", "0")))
        except (KeyError, ValueError, Conflict, HTTPException):
            await websocket.close(code=1008)
            return
        await websocket.accept()

        async def reader():
            window, count = time.monotonic(), 0
            while True:
                raw = await websocket.receive_text()
                check()
                if len(raw) > 8192:
                    raise RuntimeError("Terminal input too large")
                q = json.loads(raw)
                if time.monotonic() - window > 1:
                    window, count = time.monotonic(), 0
                count += len(raw)
                if count > 32768:
                    raise RuntimeError("Terminal input rate exceeded")
                op = q.get("op")
                if op not in {"write", "resize", "signal"}:
                    raise RuntimeError("Unsupported terminal operation")
                if (
                    op == "write"
                    and len(base64.b64decode(q.get("data", ""), validate=True)) > 4096
                ):
                    raise RuntimeError("Input too large")
                async with service.control.locks.setdefault(
                    row["lease_id"], asyncio.Lock()
                ):
                    check()
                    result = await sandbox.terminal(
                        op,
                        **{k: v for k, v in q.items() if k not in {"op", "id"}},
                        id=row["native_id"],
                    )
                await send_bounded(websocket, {"type": "ack", **result})
                with service.store.transaction() as db:
                    db.execute(
                        "UPDATE computer_sessions SET updated_at=? WHERE id=?",
                        (stamp(), sid),
                    )

        async def output():
            nonlocal offset
            while True:
                check()
                result = await sandbox.terminal(
                    "read", id=row["native_id"], offset=offset
                )
                offset = result["offset"]
                if result["data"] or result["gap"] or result["exited"]:
                    await send_bounded(websocket, {"type": "output", **result})
                if result["exited"]:
                    return
                await asyncio.sleep(0.15)

        try:
            await connected(websocket, reader(), output())
        finally:
            with anyio.CancelScope(shield=True):
                await service.close_lease(row["lease_id"])
