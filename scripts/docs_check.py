"""Check local documentation links and the generated capability table."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[1]
START = "<!-- capabilities:start -->"
END = "<!-- capabilities:end -->"


def capability_table() -> str:
    rows = json.loads((ROOT / "docs/capabilities.json").read_text(encoding="utf-8"))
    table = ["| Capability | Status | Implementation |", "| --- | --- | --- |"]
    for row in rows:
        path = ROOT / row["source"]
        if not path.is_file():
            raise ValueError(f"Capability source missing: {row['source']}")
        label = f"{path.parent.name}/{path.name}" if path.name == "__init__.py" else path.name
        table.append(f"| {row['name']} | {row['status']} | [{label}](../{row['source']}) |")
    return START + "\n" + "\n".join(table) + "\n" + END


def check(*, update=False) -> list[str]:
    errors = []
    blueprint = ROOT / "docs/architecture-blueprint.md"
    source = blueprint.read_text(encoding="utf-8")
    generated = capability_table()
    pattern = re.escape(START) + r"[\s\S]*?" + re.escape(END)
    if not re.search(pattern, source):
        errors.append("Blueprint has no generated capability table")
    elif update:
        blueprint.write_text(re.sub(pattern, lambda _: generated, source), encoding="utf-8")
    elif re.search(pattern, source).group() != generated:
        errors.append("Capability table is stale; run scripts/docs_check.py --update")
    for path in [ROOT / "README.md", *sorted((ROOT / "docs").rglob("*.md"))]:
        text = re.sub(r"```[\s\S]*?```", "", path.read_text(encoding="utf-8"))
        for match in re.finditer(r"(?<!!)\[[^\]\n]*\]\(([^)\n]+)\)", text):
            target = match.group(1).strip().split("#", 1)[0].split("?", 1)[0]
            if not target or re.match(r"[a-zA-Z]+:", target) or target.startswith("/"):
                continue
            target = unquote(target.strip("<>"))
            if not (path.parent / target).exists():
                errors.append(f"{path.relative_to(ROOT)}: missing {target}")
    return errors


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--update", action="store_true")
    args = parser.parse_args()
    errors = check(update=args.update)
    if errors:
        raise SystemExit("\n".join(errors))
    print("Documentation links and capability table are current.")


if __name__ == "__main__":
    main()
