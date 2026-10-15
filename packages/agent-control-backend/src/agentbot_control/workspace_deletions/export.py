"""Export contracts without constructing the application."""

import json
from pathlib import Path

from agentbot_control.workspace_deletions.schemas import DeletionContracts


def export(path: Path) -> None:
    path.write_text(
        json.dumps(DeletionContracts.model_json_schema(), indent=2) + "\n", encoding="utf-8"
    )
