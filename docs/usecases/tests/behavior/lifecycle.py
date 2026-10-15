from __future__ import annotations

import asyncio
import shutil
import tempfile
import time
from pathlib import Path
from typing import Any

from agentbot.adapters.anthropic import ClaudeAgentAdapter
from agentbot.adapters.microsoft import MicrosoftAgentAdapter
from agentbot.kernel import EngineRuntimeManager, SessionStore
from agentbot.registry import FrameworkRegistry
from agentbot.sandbox.docker import LABEL, DockerSessionManager

import docker
from docs.usecases.tests.behavior.constants import AZURITE_KEY, AZURITE_NAME, IMAGE, ROOT, SESSION
from docs.usecases.tests.behavior.gateway import _start_gateway
from docs.usecases.tests.behavior.scripted import Plan, PlanClient, microsoft_runner
from docs.usecases.tests.behavior.storage import BlobStore, stop_hang_proxy


def boot(context) -> None:
    context.repo_root = ROOT
    context.docker = docker.from_env()
    context.plan = Plan()
    context.account = "etlstore"
    context.blob_host = ""
    context.blobs = None
    context.azurite = None
    context.tmpdir = Path(tempfile.mkdtemp(prefix="agentbot-etl-"))
    context.kernel = _kernel(context)
    _start_gateway(context)


def reset(context) -> None:
    context.plan.name = "etl"
    context.snapshots = {}
    context.check_sas = False
    context.container_id = None
    context.pending = None
    context.command = ""
    context.hang = None
    context.engineer = None
    context.framework = "microsoft"
    if context.blob_host and context.account:
        context.plan.endpoint = f"http://{context.blob_host}:10000/{context.account}"
    if context.blobs is not None:
        context.blobs.clear()


def cleanup_scenario(context) -> None:
    engineer = getattr(context, "engineer", None)
    if engineer is not None:
        engineer.close()
        context.engineer = None
    hang = getattr(context, "hang", None)
    if hang is not None:
        stop_hang_proxy(hang)
        context.hang = None
    kernel = getattr(context, "kernel", None)
    if kernel is not None:
        asyncio.run(_settle(kernel, SESSION))
    docker_client = getattr(context, "docker", None)
    if docker_client is not None:
        _remove_session_containers(docker_client, SESSION)


def shutdown(context) -> None:
    server = getattr(context, "server", None)
    thread = getattr(context, "server_thread", None)
    if server is not None:
        server.should_exit = True
        if thread is not None:
            thread.join(timeout=10)
    docker_client = getattr(context, "docker", None)
    if docker_client is not None:
        try:
            docker_client.containers.get(AZURITE_NAME).remove(force=True)
        except docker.errors.NotFound:
            pass
        _remove_session_containers(docker_client, SESSION)
    tmpdir = getattr(context, "tmpdir", None)
    if tmpdir is not None:
        shutil.rmtree(tmpdir, ignore_errors=True)


def ensure_image(context, image: str) -> None:
    try:
        context.docker.images.get(image)
        return
    except docker.errors.ImageNotFound:
        pass
    stream = context.docker.api.build(
        path=str(context.repo_root),
        dockerfile="docker/sandbox/Dockerfile",
        tag=image,
        rm=True,
        decode=True,
    )
    for chunk in stream:
        if "error" in chunk:
            raise AssertionError(chunk["error"])


def ensure_azurite(context, account: str) -> None:
    if context.azurite is not None and context.account == account:
        return
    context.account = account
    try:
        existing = context.docker.containers.get(AZURITE_NAME)
    except docker.errors.NotFound:
        existing = None
    if existing is not None:
        existing.remove(force=True)
    context.azurite = context.docker.containers.run(
        "mcr.microsoft.com/azure-storage/azurite",
        command=[
            "azurite-blob",
            "--blobHost",
            "0.0.0.0",
            "--blobPort",
            "10000",
            "--skipApiVersionCheck",
        ],
        name=AZURITE_NAME,
        detach=True,
        ports={"10000/tcp": 10000},
        environment={"AZURITE_ACCOUNTS": f"{account}:{AZURITE_KEY}"},
    )
    host_url = f"http://127.0.0.1:10000/{account}"
    context.blobs = BlobStore(account, AZURITE_KEY, host_url)
    deadline = time.time() + 40
    last_error = "Azurite did not start"
    while time.time() < deadline:
        try:
            context.blobs.ensure_container("raw")
            return
        except Exception as exc:
            last_error = str(exc)
            time.sleep(0.4)
    raise AssertionError(last_error)


def ensure_blob_host(context, image: str) -> str:
    if context.blob_host:
        return context.blob_host
    account = context.account
    code = (
        "import urllib.error, urllib.request\n"
        f"url = 'http://host.docker.internal:10000/{account}?comp=list'\n"
        "try:\n"
        "    urllib.request.urlopen(url, timeout=10).read()\n"
        "except urllib.error.HTTPError:\n"
        "    raise SystemExit(0)\n"
        "except Exception:\n"
        "    raise SystemExit(1)\n"
    )
    try:
        context.docker.containers.run(
            image,
            ["-c", code],
            entrypoint=["python3"],
            remove=True,
            network_mode="bridge",
        )
    except docker.errors.ContainerError as exc:
        raise AssertionError(
            "the sandbox cannot reach Azurite at host.docker.internal:10000"
        ) from exc
    context.blob_host = "host.docker.internal"
    context.plan.endpoint = f"http://{context.blob_host}:10000/{context.account}"
    return context.blob_host


def session_containers(context, session_id: str) -> list[Any]:
    return context.docker.containers.list(all=True, filters={"label": f"{LABEL}={session_id}"})


def wait_until(predicate, timeout: float = 15) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return
        time.sleep(0.2)
    if not predicate():
        raise AssertionError("condition was not met")


def workspace_exists(context, session_id: str, path: str) -> bool:
    containers = session_containers(context, session_id)
    if len(containers) != 1:
        raise AssertionError(f"expected one container for {session_id}, found {len(containers)}")
    code, _output = containers[0].exec_run(["test", "-e", path])
    return code == 0


def _kernel(context) -> EngineRuntimeManager:
    plan = context.plan
    registry = FrameworkRegistry()
    registry.register_framework(
        "microsoft",
        lambda: MicrosoftAgentAdapter(runner=microsoft_runner(plan), max_tool_turns=10),
    )
    registry.register_framework(
        "anthropic",
        lambda: ClaudeAgentAdapter(client=PlanClient(plan), max_steps=8),
    )
    return EngineRuntimeManager(
        registry, DockerSessionManager(image=IMAGE), SessionStore(context.tmpdir)
    )


async def _settle(kernel: EngineRuntimeManager, session_id: str) -> None:
    for _ in range(50):
        if session_id not in kernel._busy:
            break
        await asyncio.sleep(0.1)
    await kernel.close_session(session_id)


def _remove_session_containers(docker_client, session_id: str) -> None:
    for container in docker_client.containers.list(
        all=True, filters={"label": f"{LABEL}={session_id}"}
    ):
        container.remove(force=True)
