"""Two callers of one workspace session see the same container, file, and screen."""

import uuid

import pytest

pytestmark = pytest.mark.docker


async def test_two_bots_share_one_container_file_and_screen():
    docker = pytest.importorskip("docker")
    from agentbot.sandbox.docker import DockerSessionManager

    client = docker.from_env()
    try:
        client.images.get("agentbot-sandbox")
    except Exception as exc:
        pytest.skip(f"agentbot-sandbox is not available: {exc}")
    manager = DockerSessionManager(client=client)
    sid = "shared" + uuid.uuid4().hex[:8]
    manager.note_workspace(sid, "workspace-shared")
    manager.bind(sid, "", 1)
    try:
        first = await manager.get_or_create(sid)
        await first.write_workspace_file("shared.txt", "hello-from-a")
        second = await manager.get_or_create(sid)
        assert second is first
        listed = await second.run_command("cat /workspace/shared.txt")
        assert listed.stdout == "hello-from-a"
        screen_a = await first.capture("desktop")
        screen_b = await second.capture("desktop")
        assert screen_a and screen_b
        found = client.containers.list(filters={"label": "agentbot.workspace_id=workspace-shared"})
        assert len(found) == 1
        assert found[0].labels["agentbot.session_id"] == sid
        assert "agentbot.bot_id" not in found[0].labels
        assert found[0].labels["agentbot.workspace_id"] == "workspace-shared"
    finally:
        await manager.close(sid)
