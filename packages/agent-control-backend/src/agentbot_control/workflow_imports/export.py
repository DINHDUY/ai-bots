"""Export import HTTP schemas without constructing an app or opening a database."""

import json
from pathlib import Path

from agentbot_control.workflow_imports.schemas import ImportContracts


def export(path: Path) -> None:
    path.write_text(
        json.dumps(ImportContracts.model_json_schema(), indent=2) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    import sys

    export(Path(sys.argv[1]))
