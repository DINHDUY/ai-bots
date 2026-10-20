"""Check exported schemas/types without starting the app or creating a database."""

import os
import subprocess
import tempfile
from pathlib import Path

from agentbot_control.macos.export import export as export_macos
from agentbot_control.wire import export
from agentbot_control.workflow_imports.export import export as export_imports
from agentbot_control.workspace_deletions.export import export as export_deletions

root = Path(__file__).resolve().parents[1]
frontend = root / "packages/agent-control-frontend"
schema = frontend / "src/api/events.schema.json"
generated = frontend / "src/api/events.generated.ts"
with tempfile.TemporaryDirectory() as directory:
    output = Path(directory) / "events.json"
    export(output)
    if schema.read_text(encoding="utf-8") != output.read_text(encoding="utf-8"):
        raise SystemExit(
            "Replay schema drift: export agentbot_control.wire and regenerate wire types"
        )
    export_imports(output)
    if (frontend / "src/api/imports.schema.json").read_text(encoding="utf-8") != output.read_text(
        encoding="utf-8"
    ):
        raise SystemExit(
            "Import HTTP schema drift: export agentbot_control.workflow_imports.export and regenerate wire types"
        )
    export_macos(output)
    if (frontend / "src/api/macos.schema.json").read_text() != output.read_text():
        raise SystemExit("macOS schema drift: export and regenerate contracts")
    export_deletions(output)
    if (frontend / "src/api/deletions.schema.json").read_text(encoding="utf-8") != output.read_text(
        encoding="utf-8"
    ):
        raise SystemExit("Deletion HTTP schema drift: export and regenerate deletion contracts")
macos_generated = frontend / "src/api/macos.generated.ts"
macos_before = macos_generated.read_bytes()
before = generated.read_bytes()
imports_generated = frontend / "src/api/imports.generated.ts"
imports_before = imports_generated.read_bytes()
deletions_generated = frontend / "src/api/deletions.generated.ts"
deletions_before = deletions_generated.read_bytes()
try:
    subprocess.run(
        ["npm.cmd" if os.name == "nt" else "npm", "run", "generate:wire"], cwd=frontend, check=True
    )
    if macos_before.replace(b"\r\n", b"\n") != macos_generated.read_bytes().replace(b"\r\n", b"\n"):
        raise SystemExit("macOS TypeScript drift: regenerate wire types")
    if before.replace(b"\r\n", b"\n") != generated.read_bytes().replace(b"\r\n", b"\n"):
        raise SystemExit("Replay TypeScript drift: run npm run generate:wire")
    if imports_before.replace(b"\r\n", b"\n") != imports_generated.read_bytes().replace(
        b"\r\n", b"\n"
    ):
        raise SystemExit("Import TypeScript drift: run npm run generate:wire")
    if deletions_before.replace(b"\r\n", b"\n") != deletions_generated.read_bytes().replace(
        b"\r\n", b"\n"
    ):
        raise SystemExit("Deletion TypeScript drift: run npm run generate:wire")
finally:
    macos_generated.write_bytes(macos_before)
    deletions_generated.write_bytes(deletions_before)
    generated.write_bytes(before)
    imports_generated.write_bytes(imports_before)
print("Replay schema and generated types match")
