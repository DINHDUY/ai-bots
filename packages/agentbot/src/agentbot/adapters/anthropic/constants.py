from __future__ import annotations

ENGINE = "ClaudeComputerUseEngine"


EDITOR_NAME = "str_replace_based_edit_tool"


BASH_NAME = "bash"


HALT_TEXT = "Not executed: an earlier computer action in this turn failed."


OBSERVATIONS = frozenset({"screenshot", "zoom", "cursor_position", "wait"})


SYSTEM_PROMPT = (
    "Use only the tools selected for this bot. Workspace paths are rooted at /workspace. "
    "When desktop observation is available, verify desktop actions with a screenshot."
)
