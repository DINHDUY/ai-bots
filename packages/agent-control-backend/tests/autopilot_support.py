"""Autopilot exercises the same admission and dispatch path as manual approvals."""

import uuid


def toggle(client, bid, enabled=True, revision=0, request=None):
    return client.post(
        f"/api/bots/{bid}/autopilot",
        json={
            "request_id": request or uuid.uuid4().hex,
            "enabled": enabled,
            "expected_revision": revision,
        },
    )
