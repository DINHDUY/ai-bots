#!/usr/bin/env python3
"""Local PTY owner: bounded replay, explicit groups, no publicly exposed port."""

import asyncio
import base64
import fcntl
import json
import os
import re
import signal
import struct
import termios
import time
import uuid
from pathlib import Path

SOCKET = "/tmp/agentbot-terminal.sock"
LIMIT = 256 * 1024
sessions = {}
closing = {}


def resize(fd, rows, cols):
    if not 2 <= rows <= 200 or not 2 <= cols <= 400:
        raise ValueError("Terminal size outside limits")
    fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))


def collect(s):
    try:
        chunk = os.read(s["fd"], 16384)
    except (OSError, BlockingIOError):
        chunk = b""
    if chunk:
        s["data"].extend(chunk)
        s["offset"] += len(chunk)
        del s["data"][:-LIMIT]
    else:
        asyncio.get_running_loop().remove_reader(s["fd"])
        s["exited"] = True


async def close(s):
    # Interactive job control creates separate groups in the shell's session.
    # Kill every such group, including background jobs after shell exit.
    for sig in (signal.SIGTERM, signal.SIGKILL):
        groups = {s["pid"]}
        for path in Path("/proc").glob("[0-9]*/stat"):
            try:
                fields = path.read_text().rsplit(")", 1)[1].split()
                if int(fields[3]) == s["pid"]:
                    groups.add(int(fields[2]))
            except (OSError, ValueError, IndexError):
                continue
        for group in groups:
            try:
                os.killpg(group, sig)
            except ProcessLookupError:
                pass
        await asyncio.sleep(0.1)
    try:
        os.waitpid(s["pid"], os.WNOHANG)
    except ChildProcessError:
        pass
    asyncio.get_running_loop().remove_reader(s["fd"])
    os.close(s["fd"])


async def dispatch(q):
    op = q["op"]
    if op == "health":
        return {"ok": True}
    if op == "open":
        tid = q.get("id") or uuid.uuid4().hex
        if not isinstance(tid, str) or not re.fullmatch(r"[A-Za-z0-9_]{8,80}", tid):
            raise ValueError("Invalid terminal ID")
        if tid in sessions:
            return {"id": tid, "offset": sessions[tid]["offset"]}
        if tid in closing:
            raise ValueError("Terminal is closing")
        if len(sessions) >= 2:
            raise ValueError("Terminal quota exceeded")
        rows, cols = int(q.get("rows", 24)), int(q.get("cols", 80))
        if not 2 <= rows <= 200 or not 2 <= cols <= 400:
            raise ValueError("Invalid terminal size")
        pid, fd = os.forkpty()
        if pid == 0:
            os.chdir("/workspace")
            os.execve(
                "/bin/bash",
                ["bash", "--noprofile", "--norc"],
                {
                    "HOME": "/home/agent",
                    "PATH": "/usr/local/bin:/usr/bin:/bin",
                    "TERM": "xterm-256color",
                    "LANG": "C.UTF-8",
                },
            )
        os.set_blocking(fd, False)
        resize(fd, rows, cols)
        s = dict(
            pid=pid,
            fd=fd,
            data=bytearray(),
            offset=0,
            created=time.monotonic(),
            activity=time.monotonic(),
            exited=False,
        )
        sessions[tid] = s
        asyncio.get_running_loop().add_reader(fd, collect, s)
        return {"id": tid, "offset": 0}
    if op == "close" and q.get("id") in closing:
        await asyncio.shield(closing[q["id"]])
        return {"closed": True}
    s = sessions.get(q.get("id"))
    if not s:
        if op == "close":
            return {"closed": True}
        raise ValueError("Terminal closed or unknown")
    if op == "close":
        del sessions[q["id"]]
        task = closing[q["id"]] = asyncio.create_task(close(s))
        await asyncio.shield(task)
        closing.pop(q["id"], None)
        return {"closed": True}
    if op == "read":
        offset = max(0, int(q.get("offset", 0)))
        floor = s["offset"] - len(s["data"])
        start = max(floor, min(offset, s["offset"]))
        data = bytes(s["data"][start - floor : start - floor + 16384])
        return {
            "data": base64.b64encode(data).decode(),
            "offset": start + len(data),
            "floor": floor,
            "gap": offset < floor or offset > s["offset"],
            "exited": s["exited"],
        }
    s["activity"] = time.monotonic()
    if s["exited"]:
        raise ValueError("Terminal exited")
    if op == "write":
        data = base64.b64decode(q["data"], validate=True)
        if len(data) > 4096:
            raise ValueError("Terminal input exceeds 4096 bytes")
        return {"written": os.write(s["fd"], data)}
    if op == "resize":
        resize(s["fd"], int(q["rows"]), int(q["cols"]))
    elif op == "signal" and q.get("signal") == "INT":
        os.killpg(os.tcgetpgrp(s["fd"]), signal.SIGINT)
    else:
        raise ValueError("Unsupported terminal operation")
    return {"ok": True}


async def client(reader, writer):
    try:
        raw = await asyncio.wait_for(reader.readline(), 3)
        if len(raw) > 8192:
            raise ValueError("Request too large")
        result = {"ok": True, **await dispatch(json.loads(raw))}
    except Exception as exc:
        result = {"ok": False, "error": str(exc)}
    writer.write(json.dumps(result).encode() + b"\n")
    await writer.drain()
    writer.close()
    await writer.wait_closed()


async def reap():
    while True:
        for tid, s in list(sessions.items()):
            now = time.monotonic()
            if now - s["activity"] > 300 or now - s["created"] > 3600:
                await dispatch({"op": "close", "id": tid})
        await asyncio.sleep(1)


async def main():
    try:
        os.unlink(SOCKET)
    except FileNotFoundError:
        pass
    server = await asyncio.start_unix_server(client, path=SOCKET, limit=8193)
    os.chmod(SOCKET, 0o600)
    async with server:
        await asyncio.gather(server.serve_forever(), reap())


if __name__ == "__main__":
    asyncio.run(main())
