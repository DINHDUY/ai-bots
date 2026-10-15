"""Machine-authenticated outbound bridge, independent of Windows pairing/cookies."""

import asyncio
import hashlib
import secrets
import time
import uuid
from datetime import UTC, datetime, timedelta

from agentbot.interfaces import SandboxError, TerminationUnverified
from agentbot.sandbox.bridge import (
    LEASE_SECONDS,
    MAX_FRAME,
    Assembly,
    HostHello,
    HostRequest,
    decode,
    frames,
    mutating,
)
from fastapi import HTTPException, Request, WebSocket, WebSocketDisconnect
from pydantic import Field

from agentbot_control.event_store import identifier, stamp
from agentbot_control.schemas import Command
from agentbot_control.transport import body


def token_hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


class Enroll(Command):
    code: str = Field(min_length=32, max_length=200)
    binding_id: str = Field(max_length=128)
    host_key: str = Field(min_length=32, max_length=128)


class Connection:
    def __init__(self, service, binding, hello, token, credential_id, ws):
        self.service, self.binding, self.hello, self.token = (
            service,
            binding,
            hello,
            token,
        )
        self.credential_id = credential_id
        self.channels = {"control": ws}
        self.locks = {"control": asyncio.Lock(), "data": asyncio.Lock()}
        self.pending = {}
        self.closed = False
        self.last_seen = time.monotonic()
        self.lease_ack = False

    @property
    def ready(self):
        return (
            not self.closed
            and "data" in self.channels
            and time.monotonic() - self.last_seen < LEASE_SECONDS
        )

    async def send(self, channel, message):
        ws = self.channels.get(channel)
        if ws is None or self.closed:
            raise SandboxError("Computer bridge is disconnected")
        async with self.locks[channel]:
            for frame in frames(message):
                await ws.send_text(frame)

    async def rpc(self, binding, method, arguments, action_id):
        if not self.ready:
            raise SandboxError("Computer bridge is not ready")
        if len(self.pending) >= 16:
            raise SandboxError("Computer bridge request limit reached")
        identity = uuid.uuid4().hex
        request = HostRequest(
            id=identity,
            action_id=action_id,
            binding_id=binding["id"],
            deployment=self.service.store.deployment,
            boot_id=self.hello.boot_id,
            epoch=self.hello.epoch,
            session_id=binding["session_id"],
            generation=binding["generation"],
            deadline=float(time.time() + 100),
            method=method,
            arguments=arguments,
        ).sign(self.token)
        future = asyncio.get_running_loop().create_future()
        write = mutating(method, arguments)
        self.pending[identity] = (future, write)
        sent = False
        try:
            channel = (
                "data"
                if method
                in {
                    "files",
                    "capture",
                    "terminal",
                    "read_workspace_file",
                    "write_workspace_file_checked",
                    "desktop_action",
                    "human_input",
                    "browser_click",
                    "browser_open_scoped",
                }
                else "control"
            )
            # Conservatively count a partial socket write as possibly delivered.
            sent = True
            await self.send(channel, request.model_dump())
            result = await asyncio.wait_for(asyncio.shield(future), 105)
            if result.get("outcome_unknown"):
                self.service.cloud.quarantine(
                    binding["id"],
                    "Host reported an unconfirmed action; inspect before continuing",
                )
                raise TerminationUnverified(
                    "Remote action outcome unknown; no automatic replay"
                )
            if result.get("error"):
                raise SandboxError(str(result["error"])[:500])
            return decode(result.get("result"))
        except (
            TimeoutError,
            ConnectionError,
            WebSocketDisconnect,
            asyncio.CancelledError,
            RuntimeError,
        ) as exc:
            if write and sent:
                self.service.cloud.quarantine(
                    binding["id"],
                    "Bridge response lost after input; termination is unconfirmed",
                )
                raise TerminationUnverified(
                    "Remote action response lost; inspect the computer before continuing"
                ) from exc
            raise
        finally:
            self.pending.pop(identity, None)
            if not future.done():
                future.cancel()

    async def disconnect(self):
        if self.closed:
            return
        self.closed = True
        if any(write for _, write in self.pending.values()):
            self.service.cloud.quarantine(
                self.binding["id"], "Computer bridge disconnected during a mutation"
            )
        for future, _ in list(self.pending.values()):
            if not future.done():
                future.set_exception(ConnectionError("Computer bridge disconnected"))
        for ws in list(self.channels.values()):
            try:
                await ws.close(code=1001)
            except Exception:
                pass


class ComputerAgents:
    def __init__(self, cloud):
        self.cloud, self.store = cloud, cloud.store
        self.connections = {}
        self.lock = asyncio.Lock()

    def credential(self, token):
        with self.store.transaction() as db:
            row = db.execute(
                "SELECT * FROM cloud_machine_credentials WHERE token_hash=? AND revoked_at IS NULL AND expires_at>?",
                (token_hash(token), stamp()),
            ).fetchone()
        return dict(row) if row else None

    def enrollment(self, binding, host_key):
        code = secrets.token_urlsafe(36)
        expires = (datetime.now(UTC) + timedelta(minutes=30)).isoformat()
        with self.store.transaction() as db:
            db.execute(
                "UPDATE cloud_enrollments SET consumed_at=? WHERE binding_id=? AND consumed_at IS NULL",
                (stamp(), binding["id"]),
            )
            db.execute(
                "INSERT INTO cloud_enrollments VALUES (?,?,?,?,?,NULL,?)",
                (
                    identifier("cloud_enroll"),
                    binding["id"],
                    token_hash(code),
                    host_key,
                    expires,
                    stamp(),
                ),
            )
            db.execute(
                "UPDATE computer_provider_bindings SET host_key=? WHERE id=?",
                (host_key, binding["id"]),
            )
        return {"code": code, "expires_at": expires}

    async def call(self, binding, method, arguments, action_id):
        current = self.cloud.binding(binding_id=binding["id"])
        if (
            not current
            or not current["active"]
            or (current["session_id"], current["generation"])
            != (binding["session_id"], binding["generation"])
        ):
            raise SandboxError("Cloud session generation changed")
        if current["status"] == "quarantined" and method not in {
            "cancel_commands",
            "sandbox.stop",
            "sandbox.retire",
            "sandbox.inspect",
            "receipt",
        }:
            raise TerminationUnverified(
                "Cloud computer requires reconciliation after interrupted input"
            )
        connection = self.connections.get(binding["id"])
        if not connection or not self.credential(connection.token):
            raise SandboxError("Cloud computer is offline or its credential expired")
        return await connection.rpc(current, method, arguments, action_id)

    async def shutdown(self):
        await asyncio.gather(
            *(conn.disconnect() for conn in list(self.connections.values())),
            return_exceptions=True,
        )

    def routes(self, app):
        @app.post("/api/cloud-computer-agents/enroll")
        async def enroll(request: Request):
            command = await body(request, Enroll)
            token = secrets.token_urlsafe(48)
            expires = (datetime.now(UTC) + timedelta(days=7)).isoformat()
            with self.store.transaction() as db:
                grant = db.execute(
                    "SELECT * FROM cloud_enrollments WHERE binding_id=? AND host_key=? AND secret_hash=? AND consumed_at IS NULL AND expires_at>?",
                    (
                        command.binding_id,
                        command.host_key,
                        token_hash(command.code),
                        stamp(),
                    ),
                ).fetchone()
                binding = db.execute(
                    "SELECT * FROM computer_provider_bindings WHERE id=? AND active=1",
                    (command.binding_id,),
                ).fetchone()
                if not grant or not binding or not binding["verified_owner"]:
                    raise HTTPException(
                        403, "Enrollment expired, unverified, or already used"
                    )
                db.execute(
                    "UPDATE cloud_enrollments SET consumed_at=? WHERE id=?",
                    (stamp(), grant["id"]),
                )
                db.execute(
                    "INSERT INTO cloud_machine_credentials VALUES (?,?,?,?,NULL,?)",
                    (
                        identifier("machine"),
                        command.binding_id,
                        token_hash(token),
                        expires,
                        stamp(),
                    ),
                )
            return {
                "token": token,
                "expires_at": expires,
                "binding_id": command.binding_id,
                "deployment": self.store.deployment,
                "profile": self.cloud.host_profile(dict(binding)),
            }

        @app.post("/api/cloud-computer-agents/renew")
        async def renew(request: Request):
            auth = request.headers.get("authorization", "")
            old = (
                self.credential(auth.removeprefix("Bearer "))
                if auth.startswith("Bearer ")
                else None
            )
            binding = self.cloud.binding(binding_id=old["binding_id"]) if old else None
            if not old or not binding or not binding["active"]:
                raise HTTPException(401, "Machine credential required")
            token = secrets.token_urlsafe(48)
            expires = (datetime.now(UTC) + timedelta(days=7)).isoformat()
            with self.store.transaction() as db:
                db.execute(
                    "INSERT INTO cloud_machine_credentials VALUES (?,?,?,?,NULL,?)",
                    (
                        identifier("machine"),
                        old["binding_id"],
                        token_hash(token),
                        expires,
                        stamp(),
                    ),
                )
                db.execute(
                    "UPDATE cloud_machine_credentials SET expires_at=? WHERE id=?",
                    (
                        (datetime.now(UTC) + timedelta(minutes=2)).isoformat(),
                        old["id"],
                    ),
                )
            return {"token": token, "expires_at": expires}

        @app.websocket("/api/cloud-computer-agents/connect")
        async def connect(ws: WebSocket):
            auth = ws.headers.get("authorization", "")
            token = auth.removeprefix("Bearer ") if auth.startswith("Bearer ") else ""
            credential = self.credential(token)
            if not credential or ws.headers.get("origin"):
                await ws.close(code=1008)
                return
            await ws.accept()
            conn = None
            hello = None
            timer = None
            try:
                raw = await asyncio.wait_for(ws.receive_text(), 10)
                if len(raw) > MAX_FRAME:
                    raise ValueError("Handshake too large")
                hello = HostHello.model_validate_json(raw)
                binding = self.cloud.binding(binding_id=credential["binding_id"])
                if (
                    not binding
                    or not binding["active"]
                    or hello.binding_id != binding["id"]
                    or hello.host_key != binding["host_key"]
                    or hello.deployment != self.store.deployment
                    or hello.session_id != binding["session_id"]
                    or hello.generation != binding["generation"]
                ):
                    raise ValueError("Host identity does not match its enrollment")
                profile = self.cloud.profile_for(binding)
                if hello.image != profile.image:
                    raise ValueError("Host image is not the approved digest")
                async with self.lock:
                    existing = self.connections.get(binding["id"])
                    if hello.channel == "control":
                        if existing and not existing.closed:
                            raise ValueError("A writer is already connected")
                        if binding["boot_id"] and binding["boot_id"] != hello.boot_id:
                            self.cloud.host_rebooted(binding)
                        epoch = binding["writer_epoch"] + 1
                        hello = hello.model_copy(update={"epoch": epoch})
                        with self.store.transaction() as db:
                            db.execute(
                                "UPDATE computer_provider_bindings SET boot_id=?,writer_epoch=?,updated_at=? WHERE id=?",
                                (hello.boot_id, epoch, stamp(), binding["id"]),
                            )
                        conn = Connection(
                            self, binding, hello, token, credential["id"], ws
                        )
                        self.connections[binding["id"]] = conn
                    else:
                        if (
                            not existing
                            or existing.closed
                            or existing.hello.boot_id != hello.boot_id
                            or existing.hello.epoch != hello.epoch
                            or "data" in existing.channels
                        ):
                            raise ValueError(
                                "Data channel has no matching control writer"
                            )
                        conn = existing
                        conn.channels["data"] = ws
                await ws.send_json(
                    {
                        "accepted": True,
                        "epoch": conn.hello.epoch,
                        "lease_seconds": LEASE_SECONDS,
                    }
                )

                async def heartbeat():
                    while True:
                        await asyncio.sleep(3)
                        current = self.cloud.binding(binding_id=binding["id"])
                        if (
                            not self.credential(token)
                            or not current
                            or not current["active"]
                            or time.monotonic() - conn.last_seen > LEASE_SECONDS
                        ):
                            await conn.disconnect()
                            return
                        await conn.send(
                            "control",
                            {
                                "type": "heartbeat",
                                "epoch": conn.hello.epoch,
                                "lease": current["status"] != "quarantined",
                            },
                        )

                if hello.channel == "control":
                    timer = asyncio.create_task(heartbeat())
                assembly = Assembly()
                while True:
                    value = assembly.receive(await ws.receive_text())
                    if value is None:
                        continue
                    if value.get("type") == "heartbeat" and hello.channel == "control":
                        conn.last_seen = time.monotonic()
                        if isinstance(value.get("services"), dict):
                            conn.hello.services = {
                                k: v is True
                                for k, v in value["services"].items()
                                if k
                                in {
                                    "browser",
                                    "desktop",
                                    "files",
                                    "terminal",
                                    "input",
                                    "revisions",
                                }
                            }
                        conn.lease_ack = (
                            value.get("leased") is True
                            and value.get("epoch") == conn.hello.epoch
                        )
                        container_id = value.get("container_id")
                        if isinstance(container_id, str) and len(container_id) <= 128:
                            with self.store.transaction() as db:
                                db.execute(
                                    "UPDATE computer_provider_bindings SET container_id=? WHERE id=? AND session_id=? AND generation=?",
                                    (
                                        container_id,
                                        binding["id"],
                                        value.get("session_id"),
                                        value.get("generation"),
                                    ),
                                )
                        continue
                    pending = conn.pending.get(value.get("id"))
                    if pending and not pending[0].done():
                        pending[0].set_result(value)
            except (Exception, asyncio.CancelledError):
                pass
            finally:
                if timer:
                    timer.cancel()
                    await asyncio.gather(timer, return_exceptions=True)
                if conn:
                    await conn.disconnect()
                try:
                    await ws.close()
                except Exception:
                    pass
