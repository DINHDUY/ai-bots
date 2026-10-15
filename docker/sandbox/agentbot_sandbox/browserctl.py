#!/usr/bin/env python3
"""Send one command to the in-container browser daemon."""

from __future__ import annotations

import json
import socket
import sys

SOCKET = "/tmp/agentbot-browser.sock"


def main() -> None:
    command = sys.argv[1]
    payload: dict[str, str] = {"cmd": command}
    if command == "input":
        payload["input"] = json.loads(sys.argv[2])
    if command in {"click", "open"}:
        payload["selector" if command == "click" else "url"] = sys.argv[2]
    if len(sys.argv) > 3:
        payload["origin"] = sys.argv[3]
    client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    client.settimeout(40 if command != "health" else 2)
    client.connect(SOCKET)
    client.sendall(json.dumps(payload).encode() + b"\n")
    chunks: list[bytes] = []
    while True:
        piece = client.recv(65536)
        if not piece:
            break
        chunks.append(piece)
        if b"\n" in piece:
            break
    sys.stdout.write(b"".join(chunks).decode())


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        sys.stdout.write(json.dumps({"ok": False, "error": str(exc)}))
