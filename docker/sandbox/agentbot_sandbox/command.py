#!/usr/bin/env python3
"""Supervise one shell process group; cancellation is acknowledged after exit."""

import fcntl
import json
import os
from pathlib import Path
import re
import selectors
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone

from revisions import workspace_revision

ROOT = Path("/tmp/agentbot-commands")


def kill_group(pid):
    try:
        os.killpg(pid, signal.SIGKILL)
    except ProcessLookupError:
        pass


def alive(pid):
    try:
        os.killpg(pid, 0)
        return True
    except ProcessLookupError:
        return False


def main():
    started_at = datetime.now(timezone.utc).isoformat()
    operation, command_id = sys.argv[1:3]
    if not re.fullmatch(r"[a-f0-9]{32}", command_id):
        raise ValueError("Invalid command ID")
    ROOT.mkdir(mode=0o700, exist_ok=True)
    pidfile, cancelled = ROOT / (command_id + ".pid"), ROOT / (command_id + ".cancel")
    with (ROOT / (command_id + ".lock")).open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if operation == "cancel":
            cancelled.touch()
            pid = int(pidfile.read_text()) if pidfile.exists() else None
            if pid:
                kill_group(pid)
            fcntl.flock(lock, fcntl.LOCK_UN)
            deadline = time.monotonic() + 5
            while pid and alive(pid) and time.monotonic() < deadline:
                time.sleep(0.02)
            sys.exit(2 if pid and alive(pid) else 0)
        if cancelled.exists():
            print(
                json.dumps(
                    dict(
                        command_id=command_id,
                        exit_code=137,
                        stdout="",
                        stderr="Cancelled",
                        timed_out=False,
                        cancelled=True,
                        stdout_truncated=False,
                        stderr_truncated=False,
                        started_at=started_at,
                        ended_at=datetime.now(timezone.utc).isoformat(),
                    )
                )
            )
            return
        timeout, command = float(sys.argv[3]), sys.argv[4]
        if len(sys.argv) > 5 and workspace_revision() != sys.argv[5]:
            raise ValueError("Workspace revision changed; request fresh approval")
        process = subprocess.Popen(
            ["bash", "-lc", command],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
        )
        pidfile.write_text(str(process.pid))
        fcntl.flock(lock, fcntl.LOCK_UN)
    selector = selectors.DefaultSelector()
    selector.register(process.stdout, selectors.EVENT_READ, "stdout")
    selector.register(process.stderr, selectors.EVENT_READ, "stderr")
    output = {"stdout": bytearray(), "stderr": bytearray()}
    timed_out = False
    truncated = {"stdout": False, "stderr": False}
    deadline = time.monotonic() + timeout
    try:
        while selector.get_map() or process.poll() is None:
            if time.monotonic() >= deadline:
                timed_out = True
                kill_group(process.pid)
            for key, _ in selector.select(0.05):
                data = os.read(key.fileobj.fileno(), 4096)
                if not data:
                    selector.unregister(key.fileobj)
                else:
                    target = output[key.data]
                    truncated[key.data] |= len(target) + len(data) > 16000
                    target.extend(data[: max(0, 16000 - len(target))])
        process.wait()
    finally:
        # A shell that exits cannot leave background children as untracked writers.
        kill_group(process.pid)
        process.wait()
        with (ROOT / (command_id + ".lock")).open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            pidfile.unlink(missing_ok=True)
    print(
        json.dumps(
            dict(
                command_id=command_id,
                exit_code=124 if timed_out else process.returncode,
                stdout=output["stdout"].decode(errors="replace"),
                stderr=output["stderr"].decode(errors="replace"),
                timed_out=timed_out,
                cancelled=cancelled.exists(),
                stdout_truncated=truncated["stdout"],
                stderr_truncated=truncated["stderr"],
                started_at=started_at,
                ended_at=datetime.now(timezone.utc).isoformat(),
            )
        )
    )


if __name__ == "__main__":
    main()
