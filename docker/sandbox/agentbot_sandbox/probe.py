#!/usr/bin/env python3
"""Probe each service independently; a socket path alone is not readiness."""

import json
import socket
import subprocess
from pathlib import Path


def probe():
    result = {"browser": False, "desktop": False}
    result["files"] = Path("/opt/agentbot_sandbox/files.py").is_file()
    result["terminal"] = False
    try:
        with socket.socket(socket.AF_UNIX) as client:
            client.settimeout(2)
            client.connect("/tmp/agentbot-terminal.sock")
            client.sendall(b'{"op":"health"}\n')
            result["terminal"] = bool(json.loads(client.recv(4096)).get("ok"))
    except Exception:
        pass
    try:
        with socket.socket(socket.AF_UNIX) as client:
            client.settimeout(2)
            client.connect("/tmp/agentbot-browser.sock")
            client.sendall(b'{"cmd":"health"}\n')
            result["browser"] = bool(json.loads(client.recv(4096)).get("ok"))
    except Exception:
        pass
    try:
        result["desktop"] = (
            subprocess.run(
                ["xdotool", "getdisplaygeometry"], capture_output=True, timeout=2
            ).returncode
            == 0
        )
    except Exception:
        pass
    return result


if __name__ == "__main__":
    print(json.dumps(probe()))
