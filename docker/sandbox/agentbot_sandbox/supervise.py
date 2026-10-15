#!/usr/bin/env python3
"""Own service process groups and expose individual failures to health probes."""

import os
import signal
import subprocess
import time
from pathlib import Path

children = []
stopping = False


def stop(*_):
    global stopping
    stopping = True


signal.signal(signal.SIGTERM, stop)
signal.signal(signal.SIGINT, stop)
Path("/tmp/.X11-unix").mkdir(exist_ok=True)
commands = {
    "xvfb": [
        "Xvfb",
        ":99",
        "-screen",
        "0",
        "1024x768x24",
        "-ac",
        "+extension",
        "RANDR",
    ],
    "openbox": ["openbox"],
    "browserd": ["python3", "/opt/agentbot_sandbox/browserd.py"],
    "watch_files": ["python3", "/opt/agentbot_sandbox/watch_files.py"],
    "terminald": ["python3", "/opt/agentbot_sandbox/terminald.py"],
}
for name, command in commands.items():
    with open(f"/tmp/{name}.log", "ab", buffering=0) as log:
        children.append(
            subprocess.Popen(command, stdout=log, stderr=log, start_new_session=True)
        )
    if name == "xvfb":
        time.sleep(0.4)
while not stopping:
    for child in children:
        child.poll()
    time.sleep(0.2)
for child in children:
    if child.poll() is None:
        os.killpg(child.pid, signal.SIGTERM)
for child in children:
    try:
        child.wait(timeout=3)
    except subprocess.TimeoutExpired:
        os.killpg(child.pid, signal.SIGKILL)
        child.wait()
