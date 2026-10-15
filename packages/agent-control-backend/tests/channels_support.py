import time

import pytest
from control_support import _create_bot, _key, _register


def setup(client, frameworks=("microsoft", "microsoft")):
    _register(client)
    bots = []
    for index, framework in enumerate(frameworks):
        key = _key(client, "anthropic" if framework == "anthropic" else "openai")
        response = _create_bot(
            client,
            name=["Writer", "Analyst", "Research"][index],
            framework=framework,
            credential_id=key["id"],
            tool_selection=[],
        )
        assert response.status_code == 201, response.text
        bots.append(response.json()["id"])
    wid = client.get("/api/workspaces").json()[0]["id"]
    response = client.patch(
        f"/api/workspaces/{wid}/channel",
        json={"revision": 0, "enabled": True, "enroll_bot_ids": bots},
    )
    assert response.status_code == 200, response.text
    return wid, bots


def post(client, wid, bid, request="channel_test_request", **extra):
    response = client.post(
        f"/api/workspaces/{wid}/channel/messages",
        json={
            "request_id": request,
            "recipient_id": bid,
            "text": "Please answer this question.",
            **extra,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def settled(client, wid, predicate):
    deadline = time.monotonic() + 8
    while time.monotonic() < deadline:
        response = client.get(f"/api/workspaces/{wid}/channel/snapshot")
        assert response.status_code == 200, response.text
        state = response.json()
        if predicate(state):
            return state
        time.sleep(0.03)
    pytest.fail(f"Channel did not settle: {state}")
