"""HTTPS enrollment and two outbound WSS lanes. No listening service or public ports."""

import argparse
import asyncio
import getpass
import json
import logging
import os
import secrets
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from agentbot.interfaces import TerminationUnverified
from agentbot.sandbox.bridge import (
    LEASE_SECONDS,
    MAX_FRAME,
    Assembly,
    HostHello,
    frames,
)
from websockets.asyncio.client import connect

from .host import Host, save_private

logger = logging.getLogger("agentbot.computer_agent")


def checked_url(value):
    url = urlsplit(value)
    if (
        url.scheme != "https"
        or not url.hostname
        or url.username
        or url.password
        or url.query
        or url.fragment
        or url.path not in {"", "/"}
    ):
        raise ValueError("Use the backend's HTTPS origin without credentials or a path")
    return value.rstrip("/")


async def enroll(path, backend, binding, host_key, code):
    backend = checked_url(backend)
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(
            backend + "/api/cloud-computer-agents/enroll",
            json={
                "request_id": secrets.token_hex(16),
                "binding_id": binding,
                "host_key": host_key,
                "code": code,
            },
        )
        if response.status_code != 200:
            raise RuntimeError(
                "Host enrollment failed; check the one-time grant and assigned owner"
            )
        config = response.json() | {"backend": backend, "host_key": host_key}
        save_private(path, config)
    return config


async def session(host):
    config = host.config
    url = (
        checked_url(config["backend"]).replace("https://", "wss://", 1)
        + "/api/cloud-computer-agents/connect"
    )
    headers = {"Authorization": "Bearer " + config["token"]}
    p = config["profile"]
    await host.health()
    hello = HostHello(
        binding_id=config["binding_id"],
        host_key=config["host_key"],
        boot_id=host.boot,
        deployment=config["deployment"],
        image=p["image"],
        session_id=p["session_id"],
        generation=p["generation"],
        container_id=host.container_id,
    )
    tasks = set()
    lease_seen = time.monotonic()
    async with connect(
        url,
        additional_headers=headers,
        max_size=MAX_FRAME,
        max_queue=8,
        compression=None,
    ) as control:
        await control.send(hello.model_dump_json())
        accepted = json.loads(await asyncio.wait_for(control.recv(), 10))
        host.epoch = accepted["epoch"]
        hello.channel, hello.epoch = "data", host.epoch
        async with connect(
            url,
            additional_headers=headers,
            max_size=MAX_FRAME,
            max_queue=8,
            compression=None,
        ) as data:
            await data.send(hello.model_dump_json())
            await asyncio.wait_for(data.recv(), 10)
            locks = {"control": asyncio.Lock(), "data": asyncio.Lock()}

            async def send(channel, value):
                async with locks[channel]:
                    for frame in frames(value):
                        await (control if channel == "control" else data).send(frame)

            async def action(value, channel):
                try:
                    result = await host.execute(value)
                    response = {"id": value["id"], "result": result}
                except TerminationUnverified:
                    response = {"id": value["id"], "outcome_unknown": True}
                except Exception:
                    # Do not serialize SDK exceptions, command arguments or credentials.
                    response = {
                        "id": value.get("id"),
                        "error": "Host rejected the request or its sandbox service is unavailable",
                    }
                await send(channel, response)

            async def receive(channel, socket):
                nonlocal lease_seen
                assembly = Assembly()
                async for raw in socket:
                    value = assembly.receive(raw)
                    if value is None:
                        continue
                    if channel == "control" and value.get("type") == "heartbeat":
                        if value.get("epoch") != host.epoch:
                            raise RuntimeError("Host writer fenced")
                        lease_seen = time.monotonic()
                        if value.get("lease"):
                            host.leased = True
                        elif host.leased:
                            await host.fence()
                        continue
                    if len(tasks) >= 16:
                        raise RuntimeError("Host request limit exceeded")
                    task = asyncio.create_task(action(value, channel))
                    tasks.add(task)
                    task.add_done_callback(tasks.discard)

            async def heartbeat():
                while True:
                    if datetime.fromisoformat(config["expires_at"]) < datetime.now(
                        UTC
                    ) + timedelta(days=1):
                        raise RuntimeError(
                            "Credential rotation requires a fresh authenticated connection"
                        )
                    await send(
                        "control",
                        {
                            "type": "heartbeat",
                            "services": host.services,
                            "leased": host.leased,
                            "epoch": host.epoch,
                            "container_id": host.container_id,
                            "session_id": config["profile"]["session_id"],
                            "generation": config["profile"]["generation"],
                        },
                    )
                    await asyncio.sleep(2)

            async def watchdog():
                while time.monotonic() - lease_seen < LEASE_SECONDS:
                    await asyncio.sleep(0.5)
                await host.fence()
                raise RuntimeError("Backend lease expired")

            async def health():
                while True:
                    await host.health()
                    await asyncio.sleep(5)

            loops = [
                asyncio.create_task(coro)
                for coro in (
                    receive("control", control),
                    receive("data", data),
                    heartbeat(),
                    watchdog(),
                    health(),
                )
            ]
            try:
                await asyncio.wait(loops, return_when=asyncio.FIRST_COMPLETED)
            finally:
                await host.fence()
                for task in loops + list(tasks):
                    task.cancel()
                await asyncio.gather(*loops, *list(tasks), return_exceptions=True)


async def run(path):
    config = json.loads(path.read_text())
    host = Host(config, path)
    # A previous process may have died mid-action. Stop its owned workloads first.
    await host.fence()
    try:
        while True:
            try:
                if datetime.fromisoformat(config["expires_at"]) < datetime.now(
                    UTC
                ) + timedelta(days=1):
                    async with httpx.AsyncClient(timeout=20) as client:
                        response = await client.post(
                            checked_url(config["backend"])
                            + "/api/cloud-computer-agents/renew",
                            headers={"Authorization": "Bearer " + config["token"]},
                        )
                        if response.status_code != 200:
                            raise RuntimeError("Credential renewal rejected")
                        config.update(response.json())
                        save_private(path, config)
                await session(host)
            except Exception:
                logger.warning(
                    "Host disconnected; owned workload fenced. Retrying authenticated connection."
                )
            finally:
                await host.fence()
            await asyncio.sleep(5)
    finally:
        await host.fence()
        host.db.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command", choices=["identity", "enroll", "run", "fence", "bootstrap"]
    )
    parser.add_argument(
        "--config", type=Path, default=Path("/var/lib/agentbot-host/agent.json")
    )
    args = parser.parse_args()
    if os.name != "posix" or os.geteuid() != 0:
        parser.error(
            "Run the trusted host service as root on a dedicated Linux computer"
        )
    if args.command == "identity":
        path = args.config.with_suffix(".identity.json")
        if not path.exists():
            save_private(path, {"host_key": secrets.token_hex(32)})
        print(json.loads(path.read_text())["host_key"])
    elif args.command == "enroll":
        identity = json.loads(args.config.with_suffix(".identity.json").read_text())[
            "host_key"
        ]
        asyncio.run(
            enroll(
                args.config,
                input("Backend HTTPS origin: ").strip(),
                input("Binding ID: ").strip(),
                identity,
                getpass.getpass("One-time enrollment code: "),
            )
        )
        print("Enrolled. Start the agentbot-computer-agent service.")
    elif args.command == "bootstrap":
        from .bootstrap import bootstrap

        asyncio.run(bootstrap(args.config))
    elif args.command == "fence":
        if args.config.exists():
            host = Host(json.loads(args.config.read_text()), args.config)
            asyncio.run(host.fence())
            host.db.close()
    else:
        logging.basicConfig(level=logging.INFO)
        asyncio.run(run(args.config))


if __name__ == "__main__":
    main()
