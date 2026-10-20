"""Owned-container boundary, persistent workspace and durable mutation receipts."""

import asyncio
import json
import os
import re
import sqlite3
import subprocess
import sys
from pathlib import Path

from agentbot.interfaces import SandboxError, TerminationUnverified
from agentbot.sandbox.bridge import HostRequest, digest, encode, mutating, packed
from agentbot.sandbox.docker import DockerSandbox, DockerSessionManager


def save_private(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_suffix(".tmp")
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        json.dump(value, stream)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


class OwnedDocker(DockerSessionManager):
    def __init__(self, config, client=None, *, verify_network=True):
        self.config, self.verify_network = config, verify_network
        p = config["profile"]
        super().__init__(p["image"], client)
        self.configure_scope("cloud", config["deployment"])
        self.bind(p["session_id"], p["bot_id"], p["generation"])

    def _labels(self, sid):
        return super()._labels(sid) | {"agentbot.cloud_binding": self.config["binding_id"]}

    def _start(self, sid):
        p = self.config["profile"]
        if self.verify_network:
            # Rules are installed by the root bootstrap; no container has host access.
            subprocess.run(
                ["/usr/local/sbin/agentbot-network", "check"],
                check=True,
                capture_output=True,
                timeout=10,
            )
        if sid != p["session_id"] or not re.fullmatch(r"[a-zA-Z0-9_-]+", self.config["binding_id"]):
            raise SandboxError("Unregistered sandbox identity")
        found = self._find(sid)
        if len(found) > 1:
            raise SandboxError("Ambiguous owned container")
        if found:
            container = found[0]
            if container.attrs.get("Config", {}).get("Image") != self._image:
                raise SandboxError("Existing container image differs from approved digest")
            if container.status != "running":
                container.start()
            return DockerSandbox(container, sid)
        root = Path(p["workspace_root"])
        if root.is_symlink() or root.resolve() != root or not root.is_absolute():
            raise SandboxError("Persistent workspace root is not a canonical directory")
        if p.get("storage_policy") == "managed_data_disk" and not root.is_mount():
            raise SandboxError("The registered persistent data disk is not mounted")
        directory = root / self.config["binding_id"] / str(p["generation"])
        if directory.resolve() != directory or root not in directory.parents:
            raise SandboxError("Workspace escaped its registered storage root")
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chown(directory, 1000, 1000)
        image = self._docker().images.get(self._image)
        labels = image.attrs.get("Config", {}).get("Labels", {}) or {}
        if (
            labels.get("agentbot.sandbox_protocol") != "2"
            or labels.get("agentbot.computer_protocol") != "3"
        ):
            raise SandboxError("Sandbox image protocols are incompatible")
        container = self._docker().containers.run(
            self._image,
            detach=True,
            name=f"agentbot-cloud-{self.config['binding_id']}-{p['generation']}",
            labels=self._labels(sid),
            init=True,
            user="1000:1000",
            mem_limit=f"{p['memory_mb']}m",
            nano_cpus=p["cpu_count"] * 1_000_000_000,
            pids_limit=512,
            shm_size="1g",
            cap_drop=["ALL"],
            security_opt=["no-new-privileges:true"],
            network="agentbot-workloads",
            tmpfs={"/tmp": "rw,nosuid,size=256m"},
            sysctls={"net.ipv6.conf.all.disable_ipv6": "1"},
            volumes={str(directory): {"bind": "/workspace", "mode": "rw"}},
            restart_policy={"Name": "no"},
        )
        return DockerSandbox(container, sid)

    async def fence(self):
        def stop_owned():
            # This binding only. Never stop an unrelated Docker container.
            containers = self._docker().containers.list(
                all=True,
                filters={
                    "label": [
                        f"agentbot.cloud_binding={self.config['binding_id']}",
                        f"agentbot.deployment={self.deployment}",
                        "agentbot.namespace=cloud",
                    ]
                },
            )
            for container in containers:
                if container.status == "running":
                    container.stop(timeout=2)
                    container.reload()
                    if container.status == "running":
                        raise TerminationUnverified("Owned container did not stop")
            self._sessions.clear()

        await asyncio.to_thread(stop_owned)


class Host:
    def __init__(self, config, path, manager=None):
        self.config, self.path = config, Path(path)
        if not sys.platform.startswith("linux") and manager is None:
            raise SandboxError("The Docker host agent requires Linux")
        self.manager = manager or OwnedDocker(config)
        journal = self.path.with_suffix(".receipts.sqlite")
        self.db = sqlite3.connect(journal)
        os.chmod(journal, 0o600)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS receipts (action_id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, state TEXT NOT NULL, result TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP)"
        )
        self.db.commit()
        self.lock = asyncio.Lock()
        self.leased = False
        self.services = {}
        self.container_id = ""
        self.epoch = 0
        self.boot = (
            Path("/proc/sys/kernel/random/boot_id").read_text().strip()
            if sys.platform.startswith("linux")
            else "test-host-boot"
        )

    async def fence(self):
        self.leased = False
        self.services = {}
        await self.manager.fence()

    def capabilities(self, report):
        self.container_id = report.get("container_id", "")
        services = dict(report.get("services", {}))
        # The pinned protocol-3 image supplies input; protocol-2 supplies revisions.
        services["input"] = bool(report.get("compatible") and services.get("desktop"))
        services["revisions"] = bool(
            report.get("compatible") and report.get("lifecycle") == "running"
        )
        self.services = services
        report["services"] = services
        return report

    async def health(self):
        try:
            self.capabilities(await self.manager.inspect(self.config["profile"]["session_id"]))
        except Exception:
            self.services = {}

    async def execute(self, request):
        request = HostRequest.model_validate(request)
        request.verify(
            self.config["token"],
            self.config["binding_id"],
            self.boot,
            self.epoch,
            self.config["deployment"],
        )
        p = self.config["profile"]
        transition = (
            request.method == "sandbox.ensure" and request.generation == p["generation"] + 1
        )
        if not transition and (request.session_id, request.generation) != (
            p["session_id"],
            p["generation"],
        ):
            raise SandboxError("Stale sandbox generation")
        if request.method == "receipt":
            row = self.db.execute(
                "SELECT state,result FROM receipts WHERE action_id=?",
                (request.arguments.get("action_id"),),
            ).fetchone()
            return (
                {"state": row[0], "result": json.loads(row[1]) if row[1] else None}
                if row
                else {"state": "unknown"}
            )
        writing = mutating(request.method, request.arguments)
        if (
            writing
            and request.method not in {"sandbox.stop", "sandbox.retire", "cancel_commands"}
            and not self.leased
        ):
            raise SandboxError("Host lease expired; request was not dispatched")
        # Stop/cancel has its own control lane and must not queue behind a command.
        if writing and request.method not in {"sandbox.stop", "cancel_commands"}:
            async with self.lock:
                return await self.dispatch(request, writing, transition)
        return await self.dispatch(request, writing, transition)

    async def dispatch(self, request, writing, transition=False):
        request.verify(
            self.config["token"],
            self.config["binding_id"],
            self.boot,
            self.epoch,
            self.config["deployment"],
        )
        value = {
            "session_id": request.session_id,
            "generation": request.generation,
            "method": request.method,
            "arguments": request.arguments,
        }
        checksum = digest(value)
        if writing:
            if not self.leased and request.method not in {
                "sandbox.stop",
                "sandbox.retire",
                "cancel_commands",
            }:
                raise SandboxError("Host lease expired before dispatch")
            row = self.db.execute(
                "SELECT fingerprint,state,result FROM receipts WHERE action_id=?",
                (request.action_id,),
            ).fetchone()
            if row:
                if row[0] != checksum:
                    raise SandboxError("Action ID reused with different arguments")
                if row[1] != "completed":
                    raise TerminationUnverified(
                        "Earlier action outcome is unknown; action will not be replayed"
                    )
                return json.loads(row[2])
            self.db.execute(
                "INSERT INTO receipts(action_id,fingerprint,state) VALUES (?,?,'started')",
                (request.action_id, checksum),
            )
            self.db.commit()  # receipt precedes any mutation
        try:
            p = self.config["profile"]
            if request.method == "sandbox.ensure":
                supplied = request.arguments
                expected = p | {
                    "session_id": request.session_id,
                    "generation": request.generation,
                }
                if supplied != expected:
                    raise SandboxError("Ensure does not match the registered host profile")
                if transition:
                    old = await self.manager.inspect(p["session_id"])
                    if old["lifecycle"] != "missing":
                        raise SandboxError("Previous generation has not been retired")
                    p.update(session_id=request.session_id, generation=request.generation)
                    save_private(self.path, self.config)
                    self.manager.bind(request.session_id, p["bot_id"], request.generation)
                await self.manager.get_or_create(request.session_id)
                result = await self.manager.inspect(request.session_id)
                self.capabilities(result)
            elif request.method == "sandbox.inspect":
                result = await self.manager.inspect(request.session_id)
                self.capabilities(result)
            elif request.method == "sandbox.retire":
                await self.manager.close(request.session_id)
                self.services = {}
                result = await self.manager.inspect(request.session_id)
                if result["lifecycle"] != "missing":
                    raise TerminationUnverified("Sandbox retirement not confirmed")
            elif request.method == "sandbox.stop":
                await self.fence()
                result = {"stopped": True}
            else:
                sandbox = await self.manager.existing(request.session_id)
                result = await getattr(sandbox, request.method)(**request.arguments)
            result = encode(result)
            if writing:
                self.db.execute(
                    "UPDATE receipts SET state='completed',result=? WHERE action_id=?",
                    (packed(result), request.action_id),
                )
                # Preserve unresolved receipts; bound completed data retained for deduplication.
                self.db.execute(
                    "UPDATE receipts SET result=NULL,state='expired' WHERE action_id IN (SELECT action_id FROM receipts WHERE state='completed' ORDER BY created_at DESC LIMIT -1 OFFSET 500)"
                )
                self.db.commit()
            return result
        except BaseException:
            if writing:
                self.leased = False
                await self.fence()
                raise TerminationUnverified(
                    "Host mutation did not produce a durable result; inspect before continuing"
                )
            raise
