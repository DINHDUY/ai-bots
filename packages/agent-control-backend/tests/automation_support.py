import time

import pytest


def wait_job(client, rid, state):
    deadline = time.monotonic() + 6
    while time.monotonic() < deadline:
        jobs = client.get(f"/api/routines/{rid}/history").json()
        if jobs and jobs[0]["state"] in state:
            return jobs[0]
        time.sleep(0.03)
    pytest.fail(f"Job did not settle: {jobs}")
