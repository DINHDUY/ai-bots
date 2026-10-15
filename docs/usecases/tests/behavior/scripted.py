from __future__ import annotations

from typing import Any

from agentbot.adapters.anthropic import ModelTurn, ToolUse

from docs.usecases.tests.behavior.constants import ETL_SCRIPT


class Plan:
    """Tool sequence the use case requires, read by the real adapters."""

    def __init__(self) -> None:
        self.name = "etl"
        self.endpoint = ""
        self.raw_sas = ""
        self.curated_sas = ""

    def env_file(self) -> str:
        return (
            f"RAW_READ_SAS={self.raw_sas}\n"
            f"CURATED_WRITE_SAS={self.curated_sas}\n"
            f"BLOB_ENDPOINT={self.endpoint}\n"
        )

    def script_for(self, date: str) -> str:
        return ETL_SCRIPT.replace('DATE = "2026-10-06"', f'DATE = "{date}"', 1)


def microsoft_runner(plan: Plan):
    async def runner(tools, prompt, context, on_text):
        kind = plan.name
        if kind == "deny":
            return await tools["run_terminal_command"](
                "python3 /workspace/etl_orders.py --print RAW_READ_SAS"
            )
        if kind == "list":
            return await tools["run_terminal_command"]("ls -A /workspace")
        if kind == "seed":
            await tools["mutate_file"]("/workspace/azure.env", plan.env_file())
            await tools["mutate_file"]("/workspace/etl_orders.py", plan.script_for("2026-10-06"))
            return "seeded"
        if kind == "rerun":
            await tools["mutate_file"]("/workspace/etl_orders.py", plan.script_for("2026-10-07"))
            return await tools["run_terminal_command"]("python3 /workspace/etl_orders.py")
        await tools["mutate_file"]("/workspace/azure.env", plan.env_file())
        await tools["mutate_file"]("/workspace/etl_orders.py", plan.script_for("2026-10-06"))
        return await tools["run_terminal_command"]("python3 /workspace/etl_orders.py")

    return runner


def _tool(tool_id: str, name: str, payload: dict[str, Any]) -> ToolUse:
    return ToolUse(id=tool_id, name=name, toolset_name=None, input=payload)


def _editor(tool_id: str, path: str, file_text: str) -> ToolUse:
    return _tool(
        tool_id,
        "str_replace_based_edit_tool",
        {"command": "create", "path": path, "file_text": file_text},
    )


def _bash(tool_id: str, command: str) -> ToolUse:
    return _tool(tool_id, "bash", {"command": command})


class PlanClient:
    """Anthropic completion client that issues the use case's tool sequence."""

    def __init__(self, plan: Plan) -> None:
        self._turns = _turns_for(plan)

    async def complete(self, *, messages: list[dict[str, Any]], system: str) -> ModelTurn:
        if self._turns:
            return self._turns.pop(0)
        return ModelTurn(stop_reason="end_turn", text="published", tool_uses=[])


def _turns_for(plan: Plan) -> list[ModelTurn]:
    if plan.name == "deny":
        bash = _bash("b1", "python3 /workspace/etl_orders.py --print RAW_READ_SAS")
        return [ModelTurn(stop_reason="tool_use", text="Checking the command.", tool_uses=[bash])]
    if plan.name == "list":
        bash = _bash("b1", "ls -A /workspace")
        return [ModelTurn(stop_reason="tool_use", text="Listing the workspace.", tool_uses=[bash])]
    if plan.name == "seed":
        writes = [
            _editor("e1", "/workspace/azure.env", plan.env_file()),
            _editor("e2", "/workspace/etl_orders.py", plan.script_for("2026-10-06")),
        ]
        return [
            ModelTurn(stop_reason="tool_use", text="Writing the workspace files.", tool_uses=writes)
        ]
    if plan.name == "rerun":
        rewrite = _editor("e1", "/workspace/etl_orders.py", plan.script_for("2026-10-07"))
        bash = _bash("b1", "python3 /workspace/etl_orders.py")
        return [
            ModelTurn(
                stop_reason="tool_use", text="Rerunning the pipeline.", tool_uses=[rewrite, bash]
            )
        ]
    writes = [
        _editor("e1", "/workspace/azure.env", plan.env_file()),
        _editor("e2", "/workspace/etl_orders.py", plan.script_for("2026-10-06")),
        _bash("b1", "python3 /workspace/etl_orders.py"),
    ]
    return [
        ModelTurn(stop_reason="tool_use", text="Writing the orders pipeline.", tool_uses=writes)
    ]
