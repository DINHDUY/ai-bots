"""Bounded inherited IPC; the supervisor can kill a blocked worker independently."""

from __future__ import annotations

import asyncio
import json
import os
import struct
import sys
import time
from pathlib import Path

from agentbot_macos.protocol import MAX_FRAME, packed
from agentbot_macos.results import NotDispatched


class Worker:
    def __init__(self, source: Path, manifest: Path):
        self.source, self.manifest = source, manifest
        self.process = None
        self.lock = asyncio.Lock()
        self.fence = 0

    async def stop(self):
        self.fence += 1
        process, self.process = self.process, None
        if process and process.returncode is None:
            process.kill()
            await asyncio.wait_for(process.wait(), 3)

    async def call(self, method: str, arguments: dict, check=None, deadline: float | None = None):
        generation = self.fence
        async with self.lock:
            if generation != self.fence:
                raise NotDispatched("Worker stopped before dispatch")
            if check:
                check()
            if self.process is None:
                environment = {
                    k: v
                    for k, v in os.environ.items()
                    if not any(
                        s in k.upper() for s in ("KEY", "TOKEN", "SECRET", "PASSWORD", "PYTHONPATH")
                    )
                }
                environment["PYTHONPATH"] = str(Path(__file__).resolve().parents[1])
                self.process = await asyncio.create_subprocess_exec(
                    sys.executable,
                    "-m",
                    "agentbot_macos.worker",
                    str(self.source),
                    str(self.manifest),
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.DEVNULL,
                    env=environment,
                )
            if generation != self.fence:
                await self.stop()
                raise NotDispatched("Worker stopped during startup")
            process = self.process
            assert process.stdin is not None and process.stdout is not None
            if check:
                check()
            payload = packed(
                {"method": method, "arguments": arguments, "deadline": deadline or time.time() + 30}
            ).encode()
            if len(payload) > MAX_FRAME:
                raise ValueError("Worker request exceeds limit")
            try:
                process.stdin.write(struct.pack("!I", len(payload)) + payload)
                await process.stdin.drain()
                header = await asyncio.wait_for(process.stdout.readexactly(4), 35)
                length = struct.unpack("!I", header)[0]
                if length > MAX_FRAME:
                    raise ValueError("Worker response exceeds limit")
                value = json.loads(await asyncio.wait_for(process.stdout.readexactly(length), 10))
                if value.get("error"):
                    raise RuntimeError(value["error"])
                return value["result"]
            except BaseException:
                await self.stop()
                raise


def main():
    from agentbot_macos.actions import MacAction
    from agentbot_macos.native import NativeRuntime
    from agentbot_macos.oi_bridge import OpenInterface
    from agentbot_macos.planner import Planner

    source, manifest = map(Path, sys.argv[1:3])
    output = sys.stdout.buffer
    sys.stdout = sys.stderr
    oi = OpenInterface(source, manifest)
    native, planner = NativeRuntime(oi), Planner(oi.context())
    while header := sys.stdin.buffer.read(4):
        if len(header) != 4:
            return
        size = struct.unpack("!I", header)[0]
        if size > MAX_FRAME:
            return
        raw = sys.stdin.buffer.read(size)
        if len(raw) != size:
            return
        try:
            request = json.loads(raw)
            if request["deadline"] < time.time():
                raise ValueError("Worker deadline expired")
            args = request["arguments"]
            method = request["method"]
            if method in {"observe", "capture"}:
                result = native.observe(args["scope"], args["window"], args["revision"])
                if method == "capture":
                    result = result["capture"]
            elif method == "execute":
                result = native.execute(
                    MacAction.model_validate(args["action"]),
                    args["scope"],
                    args["window"],
                    args["revision"],
                    args["expires_at"],
                )
            elif method == "detect_ui":
                result = native.detect(args.get("query", ""))
            elif method == "planner":
                operation = args.pop("operation")
                if operation == "start":
                    result = planner.start(**args)
                elif operation == "prompt":
                    result = planner.prompt(args["observation"])
                elif operation == "response":
                    try:
                        result = planner.response(args["response"])
                    except ValueError:
                        result = {
                            "proposal_rejected": True,
                            "text": "Return one valid macOS action for the current observation",
                        }
                elif operation == "result":
                    result = planner.result(args["result"])
                else:
                    raise ValueError("Unknown planning operation")
            else:
                raise ValueError("Unknown worker operation")
            reply = {"result": result}
        except Exception as exc:
            reply = {"error": str(exc)[:500]}
        payload = packed(reply).encode()
        if len(payload) > MAX_FRAME:
            payload = packed({"error": "Worker response exceeds limit"}).encode()
        output.write(struct.pack("!I", len(payload)) + payload)
        output.flush()


if __name__ == "__main__":
    main()
