"""Test-only composite extension; no application catalog entry is required."""

from agentbot.interfaces import ActionResult
from agentbot.tools.context import ToolAccess, ToolExecutionContext
from agentbot.tools.registry import ToolSpec
from agentbot_tools.registry import REGISTRY

WORKFLOW = ToolSpec(
    "test.workflow", "Test workflow", "run_test_task", "Run test task",
    "Exercise two actions under one selected tool.", ("microsoft",),
    ("file_write", "bash"), ("write_workspace_file", "run_command"),
)


def workflow(context: ToolExecutionContext):
    async def run_test_task(message: str) -> str:
        """Write and run a small test script."""
        path = "/workspace/test_task.py"
        content = f"print({message!r})"

        async def write():
            await context.sandbox.write_workspace_file(path, content)
            return ActionResult(True, "Prepared test script")

        result = await context.action("file_write", {"path": path, "content": content}, path, write)
        if not result.ok:
            return result.text
        return await context.run_terminal_command(f"python3 {path}")

    return run_test_task


def access(bindings, *, validate=None):
    return ToolAccess(
        bindings, validate=validate, registry={**REGISTRY, WORKFLOW.key: WORKFLOW},
        factories={WORKFLOW.tool_id: workflow},
    )
