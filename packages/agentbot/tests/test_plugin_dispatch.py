"""Anthropic dispatches a selected CLI factory through action approval."""

import shlex

from agentbot.adapters.anthropic import ClaudeAgentAdapter, ModelTurn, ToolUse
from agentbot.events import RealTimeEventStreamer
from agentbot.tools.catalog import ToolCatalog
from agentbot_tools.cli import parse_manifest
from fakes import FakeSandbox


class Scripted:
    def __init__(self, turns):
        self.turns = list(turns)

    async def complete(self, *, messages, system):
        return self.turns.pop(0)


async def test_anthropic_runs_selected_cli_tool_after_approval(tmp_path):
    path = tmp_path / "list_dir.toml"
    path.write_text(
        """
tool_id = "list_dir"
name = "List directory"
description = "List one workspace directory with ls."
binary = "ls"
argv = ["ls", "{path}"]

[parameters.path]
description = "Workspace directory"
required = true
max_length = 200
""".strip(),
        encoding="utf-8",
    )
    spec, factory = parse_manifest(path)
    access = ToolCatalog({spec.key: spec}, {spec.tool_id: factory}).access(
        [
            {
                "library_id": spec.library_id,
                "tool_id": spec.tool_id,
                "version": spec.version,
                "configuration": {},
                "ready": True,
            }
        ]
    )
    assert access.function_schemas()[0]["name"] == "list_dir"
    sandbox = FakeSandbox()
    streamer = RealTimeEventStreamer()
    streamer.context.tool_access = access
    client = Scripted(
        [
            ModelTurn(
                "tool_use",
                "",
                [ToolUse("t1", "list_dir", None, {"path": "/workspace/a b"})],
            ),
            ModelTurn("end_turn", "done", []),
        ]
    )
    adapter = ClaudeAgentAdapter(client=client)
    await adapter.initialize(sandbox, [], streamer)
    frames = []
    async for frame in adapter.execute_step("list it"):
        frames.append(frame)
        if frame["event"] == "approval_required":
            assert frame["action"] == "cli.list_dir"
            streamer.resolve(frame["approval_id"], True)
    assert sandbox.commands == ["ls " + shlex.quote("/workspace/a b")]
    assert any(frame.get("type") == "RESULT" for frame in frames)
