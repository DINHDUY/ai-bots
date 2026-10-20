"""Private Unix socket for local status/Stop; never exposes a mutation bypass."""

import asyncio
import ctypes
import hmac
import json
import os
import secrets
import socket
from pathlib import Path


def same_user(sock) -> bool:
    libc = ctypes.CDLL(None)
    uid, gid = ctypes.c_uint(), ctypes.c_uint()
    return (
        libc.getpeereid(sock.fileno(), ctypes.byref(uid), ctypes.byref(gid)) == 0
        and uid.value == os.getuid()
    )


async def serve(root: Path, companion):
    token = secrets.token_urlsafe(32)
    key = root / "control.key"
    key.write_text(token)
    os.chmod(key, 0o600)
    path = root / "control.sock"
    path.unlink(missing_ok=True)

    async def handle(reader, writer):
        try:
            if not same_user(writer.get_extra_info("socket")):
                return
            raw = await asyncio.wait_for(reader.readline(), 2)
            if len(raw) > 4096:
                return
            request = json.loads(raw)
            if not hmac.compare_digest(str(request.get("token", "")), token):
                return
            if request.get("method") == "stop":
                await companion.local_stop()
            elif request.get("method") != "status":
                return
            result = {
                "status": companion.status,
                "state": companion.hello().model_dump(
                    exclude={"epoch", "device_id", "console_session"}
                ),
            }
            writer.write(json.dumps(result).encode() + b"\n")
            await writer.drain()
        except (ValueError, TimeoutError, ConnectionError):
            pass
        finally:
            writer.close()
            await writer.wait_closed()

    server = await asyncio.start_unix_server(handle, path=path, limit=4097)
    os.chmod(path, 0o600)
    try:
        async with server:
            await server.serve_forever()
    finally:
        path.unlink(missing_ok=True)
        key.unlink(missing_ok=True)


def request(root: Path, method: str) -> dict:
    token = (root / "control.key").read_text()
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.settimeout(5)
        client.connect(str(root / "control.sock"))
        client.sendall(json.dumps({"method": method, "token": token}).encode() + b"\n")
        return json.loads(client.recv(8192))
