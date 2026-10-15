"""Native Job Object qualification using only owned sleeping test processes."""

import subprocess
import sys
import time
from pathlib import Path


def check():
    import psutil
    from agentbot_windows.win_session import worker_job

    parent = subprocess.Popen(
        [sys.executable, str(Path(__file__).resolve()), "--child"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    job, child = None, None
    try:
        job = worker_job(parent.pid)
        parent.stdin.write("start\n")
        parent.stdin.flush()
        child = psutil.Process(int(parent.stdout.readline()))
        job.Close()
        job = None
        parent.wait(timeout=3)
        assert child.is_running(), (
            "Worker cleanup killed the launched application surrogate"
        )
        print(
            "PASS: closing the companion's job kills its worker and preserves the launched application surrogate"
        )
    finally:
        if job is not None:
            job.Close()
        if parent.poll() is None:
            parent.kill()
            parent.wait()
        if child and child.is_running():
            child.terminate()
            child.wait(timeout=3)


if __name__ == "__main__":
    if "--child" in sys.argv:
        sys.stdin.readline()
        child = subprocess.Popen(
            [sys.executable, "-c", "import time;time.sleep(120)"],
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        print(child.pid, flush=True)
        time.sleep(120)
    else:
        check()
