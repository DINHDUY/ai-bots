"""Export macOS contracts without starting services or importing native libraries."""

import json
from pathlib import Path

from agentbot_control.macos.contracts import MacContracts


def export(path: Path) -> None:
    path.write_text(json.dumps(MacContracts.model_json_schema(), indent=2) + "\n", encoding="utf-8")
