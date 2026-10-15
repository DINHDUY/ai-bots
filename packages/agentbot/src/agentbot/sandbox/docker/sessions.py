from __future__ import annotations

import asyncio
import os
from typing import Any

from agentbot.interfaces import (
    SandboxError,
)
from agentbot.sandbox.docker.client import DockerSandbox
from agentbot.sandbox.docker.constants import LABEL, logger


class DockerSessionManager:
    """Get-or-create a labeled container for each session id."""

    def __init__(self, image: str | None = None, client: Any | None = None) -> None:
        self._image = image or os.getenv("SANDBOX_IMAGE", "agentbot-sandbox")
        self._client = client
        self._sessions: dict[str, DockerSandbox] = {}
        self.namespace = "gateway"
        self.deployment = "gateway"
        self.bindings: dict[str, tuple[str, int]] = {}
        self.workspace_labels: dict[str, str] = {}
        self.legacy: dict[str, dict[str, str]] = {}

    def configure_scope(self, namespace: str, deployment: str) -> None:
        if self._sessions:
            raise RuntimeError("Cannot change the namespace of active sandboxes.")
        self.namespace, self.deployment = namespace, deployment

    def bind(self, session_id: str, bot_id: str, generation: int) -> None:
        self.bindings[session_id] = (bot_id, generation)

    def note_workspace(self, session_id: str, workspace_id: str) -> None:
        self.workspace_labels[session_id] = workspace_id

    def _labels(self, session_id: str) -> dict[str, str]:
        labels = {
            LABEL: session_id,
            "agentbot.namespace": self.namespace,
            "agentbot.deployment": self.deployment,
        }
        if session_id in self.workspace_labels:
            labels["agentbot.workspace_id"] = self.workspace_labels[session_id]
            if session_id in self.bindings:
                labels["agentbot.generation"] = str(self.bindings[session_id][1])
            return labels
        if session_id in self.bindings:
            bot_id, generation = self.bindings[session_id]
            if bot_id:
                labels.update({"agentbot.bot_id": bot_id, "agentbot.generation": str(generation)})
        return labels

    def _find(self, session_id: str):
        mapping = self.legacy.get(session_id)
        if mapping:
            try:
                container = self._docker().containers.get(mapping["container_id"])
            except Exception as exc:
                if getattr(exc, "status_code", None) == 404:
                    return []
                raise
            labels = container.labels or {}
            if (
                labels.get(LABEL) != mapping["bot_id"]
                or labels.get("agentbot.namespace")
                or container.name != f"agentbot-{mapping['bot_id']}"
            ):
                raise SandboxError("Legacy sandbox mapping no longer matches its catalog identity.")
            return [container]
        return self._docker().containers.list(
            all=True,
            filters={"label": [f"{k}={v}" for k, v in self._labels(session_id).items()]},
        )

    async def legacy_candidate(self, bot_id: str):
        def find():
            candidates = self._docker().containers.list(
                all=True, filters={"label": f"{LABEL}={bot_id}"}
            )
            candidates = [
                c
                for c in candidates
                if not (c.labels or {}).get("agentbot.namespace") and c.name == f"agentbot-{bot_id}"
            ]
            if len(candidates) == 1:
                return {"container_id": candidates[0].id, "bot_id": bot_id}
            return None

        return await asyncio.to_thread(find)

    async def reconcile(self, session_id: str, uncertain: bool) -> str:
        def inspect():
            found = self._find(session_id)
            if not found:
                return "missing"
            if len(found) != 1:
                return "failed"
            container = found[0]
            if uncertain:
                container.stop(timeout=5)
                container.reload()
                return "failed"
            return "running" if container.status == "running" else "failed"

        return await asyncio.to_thread(inspect)

    def _docker(self) -> Any:
        if self._client is None:
            import docker

            self._client = docker.from_env()
        return self._client

    async def get_or_create(self, session_id: str) -> DockerSandbox:
        existing = self._sessions.get(session_id)
        if existing is not None:
            return existing
        sandbox = await asyncio.to_thread(self._start, session_id)
        await self.wait_ready(sandbox)
        self._sessions[session_id] = sandbox
        return sandbox

    async def wait_ready(self, sandbox):
        for _ in range(60):
            try:
                report = await sandbox.service_health()
                if report.get("browser") and report.get("desktop"):
                    return
            except Exception:
                pass
            await asyncio.sleep(0.25)
        raise SandboxError("Sandbox services did not become ready")

    async def existing(self, session_id):
        found = await asyncio.to_thread(self._find, session_id)
        if len(found) != 1:
            raise SandboxError("Computer missing or ambiguous")
        container = found[0]
        await asyncio.to_thread(container.reload)
        if container.status != "running":
            raise SandboxError("Computer is not running")
        cached = self._sessions.get(session_id)
        if cached:
            cached._container = container
            return cached
        sandbox = DockerSandbox(container, session_id)
        self._sessions[session_id] = sandbox
        return sandbox

    async def inspect(self, session_id):
        found = await asyncio.to_thread(self._find, session_id)
        if not found:
            return {
                "lifecycle": "missing",
                "services": {},
                "started_at": None,
                "compatible": False,
            }
        if len(found) != 1:
            raise SandboxError("Ambiguous computer identity")
        container = found[0]
        await asyncio.to_thread(container.reload)
        report = {
            "lifecycle": container.status,
            "container_id": container.id,
            "started_at": container.attrs["State"].get("StartedAt"),
            "services": {},
            "compatible": (container.labels or {}).get("agentbot.computer_protocol") == "3",
        }
        if container.status == "running" and report["compatible"]:
            report["services"] = await DockerSandbox(container, session_id).service_health()
        return report

    async def hibernate(self, session_id):
        found = await asyncio.to_thread(self._find, session_id)
        if len(found) != 1:
            raise SandboxError("Computer missing or ambiguous")
        await asyncio.to_thread(found[0].stop, timeout=5)
        await asyncio.to_thread(found[0].reload)
        if found[0].status not in {"exited", "created"}:
            raise SandboxError("Computer stop was not confirmed")
        self._sessions.pop(session_id, None)

    async def resume(self, session_id):
        found = await asyncio.to_thread(self._find, session_id)
        if len(found) != 1:
            raise SandboxError("Retained computer missing or ambiguous")
        if found[0].status != "running":
            await asyncio.to_thread(found[0].start)
        await asyncio.to_thread(found[0].reload)
        sandbox = DockerSandbox(found[0], session_id)
        await self.wait_ready(sandbox)
        self._sessions[session_id] = sandbox
        return sandbox

    def _start(self, session_id: str) -> DockerSandbox:
        client = self._docker()
        found = self._find(session_id)
        if found:
            container = found[0]
            if container.status != "running":
                container.start()
            logger.info("Reattached isolated sandbox session boundary: VM-%s", session_id)
            return DockerSandbox(container, session_id)

        container = client.containers.run(
            self._image,
            detach=True,
            name=f"agentbot-{self.namespace}-{self.deployment}-{session_id}",
            labels=self._labels(session_id),
            init=True,
            mem_limit="2g",
            nano_cpus=1_000_000_000,
            pids_limit=512,
            shm_size="1g",
            cap_drop=["ALL"],
            security_opt=["no-new-privileges:true"],
            network_mode="bridge",
            tmpfs={"/tmp": "rw,nosuid,size=256m"},
        )
        logger.info("Initialized isolated sandbox session boundary: VM-%s", session_id)
        return DockerSandbox(container, session_id)

    async def close(self, session_id: str) -> None:
        sandbox = self._sessions.pop(session_id, None)
        if sandbox is not None:
            await sandbox.close()
            return
        await asyncio.to_thread(self._remove_labeled, session_id)

    def _remove_labeled(self, session_id: str) -> None:
        for container in self._find(session_id):
            container.remove(force=True)
