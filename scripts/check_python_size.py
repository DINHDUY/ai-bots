"""Measure maintained Python files and enforce size and test-source boundaries."""

from __future__ import annotations

import argparse
import ast
import io
import json
import subprocess
import sys
import tokenize
from dataclasses import asdict, dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if __package__ in {None, ""}:
    sys.path.insert(0, str(ROOT))

from scripts.repository_rules import source_violations

SPLIT_AT = 450
MAX_ACTIVE = 500
IGNORED_TOKENS = {
    tokenize.COMMENT,
    tokenize.NL,
    tokenize.NEWLINE,
    tokenize.INDENT,
    tokenize.DEDENT,
    tokenize.ENDMARKER,
    tokenize.ENCODING,
}


@dataclass(frozen=True)
class Measurement:
    path: str
    active: int
    physical: int


def active_lines(source: str) -> int:
    tree = ast.parse(source)
    lines = source.splitlines()
    docstrings = []

    def position(line: int, byte_column: int) -> tuple[int, int]:
        return line, len(lines[line - 1].encode()[:byte_column].decode())

    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.body:
                first = node.body[0]
                if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant):
                    if isinstance(first.value.value, str):
                        # Include parentheses and concatenated literals in a docstring.
                        # AST columns are UTF-8 bytes; tokenizer columns are characters.
                        docstrings.append(
                            (
                                position(first.lineno, first.col_offset),
                                position(first.end_lineno, first.end_col_offset),
                            )
                        )
    counted = set()
    for token in tokenize.generate_tokens(io.StringIO(source).readline):
        if token.type in IGNORED_TOKENS:
            continue
        if any(start <= token.start and token.end <= end for start, end in docstrings):
            continue
        counted.update(
            number
            for number in range(token.start[0], token.end[0] + 1)
            if number <= len(lines) and lines[number - 1].strip()
        )
    return len(counted)


def maintained_files(root: Path) -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
        cwd=root,
        check=True,
        capture_output=True,
    )
    names = set(result.stdout.decode("utf-8").split("\0")) - {""}
    return sorted(root / name for name in names if (root / name).is_file())


def measure(root: Path, files: list[Path]) -> list[Measurement]:
    rows = []
    for path in files:
        if path.suffix != ".py":
            continue
        with tokenize.open(path) as stream:
            source = stream.read()
        rows.append(
            Measurement(
                path.relative_to(root).as_posix(), active_lines(source), len(source.splitlines())
            )
        )
    return sorted(rows, key=lambda row: (-row.active, row.path))


def size_violation(row: Measurement) -> str | None:
    if row.active > MAX_ACTIVE:
        return f"{row.path}: {row.active} active lines exceed maximum {MAX_ACTIVE}"
    if row.active >= SPLIT_AT:
        return f"{row.path}: {row.active} active lines require splitting at {SPLIT_AT}"
    return None


def check(root: Path) -> tuple[list[Measurement], list[str]]:
    files = maintained_files(root)
    rows = measure(root, files)
    errors = [error for row in rows if (error := size_violation(row))]
    errors.extend(source_violations(root, files))
    return rows, errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, help="Write the measured inventory as JSON")
    args = parser.parse_args()
    rows, errors = check(ROOT)
    if args.report:
        args.report.write_text(
            json.dumps([asdict(row) for row in rows], indent=2) + "\n", encoding="utf-8"
        )
    if errors:
        print("\n".join(errors))
        return 1
    print(f"{len(rows)} Python files below {SPLIT_AT} active lines; tests remain outside source.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
