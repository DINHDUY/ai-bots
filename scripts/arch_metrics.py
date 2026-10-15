"""Reproducible architecture measurements; counts are signals, not correctness proofs."""

from __future__ import annotations

import argparse
import ast
import json
import os
import platform
import subprocess
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONTROL = ROOT / "packages/agent-control-backend/src/agentbot_control"


def transaction_calls(node: ast.AST) -> int:
    count = 0
    for child in ast.iter_child_nodes(node):
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        if isinstance(child, ast.With):
            count += sum(
                isinstance(item.context_expr, ast.Call)
                and isinstance(item.context_expr.func, ast.Attribute)
                and item.context_expr.func.attr == "transaction"
                for item in child.items
            )
        count += transaction_calls(child)
    return count


def measure(revision: str | None = None) -> dict:
    ref = subprocess.check_output(
        ["git", "rev-parse", revision or "HEAD"], cwd=ROOT, text=True
    ).strip()
    result = {
        "revision": ref,
        "source": "committed" if revision else "working_tree",
        "measured_at": datetime.now(UTC).isoformat(),
        "environment": {
            "os": platform.platform(),
            "python": platform.python_version(),
            "logical_cpus": os.cpu_count(),
        },
        "async_transactions": 0,
        "runtime_dependencies": [],
        "untyped_service_fields": [],
        "sql_modules": {},
        "public_return_annotations": {"typed": 0, "total": 0},
        "module_lines": {},
    }
    if revision:
        names = subprocess.check_output(
            ["git", "ls-tree", "-r", "--name-only", ref, str(CONTROL.relative_to(ROOT))],
            cwd=ROOT,
            text=True,
        ).splitlines()
        paths = [ROOT / name for name in names if name.endswith(".py")]
    else:
        paths = sorted(CONTROL.rglob("*.py"))
    source_hash = sha256()
    for path in paths:
        source = (
            subprocess.check_output(
                ["git", "show", f"{ref}:{path.relative_to(ROOT).as_posix()}"], cwd=ROOT
            ).decode("utf-8")
            if revision
            else path.read_text(encoding="utf-8")
        )
        name = path.relative_to(CONTROL).as_posix()
        source_hash.update(name.encode() + b"\0" + source.replace("\r\n", "\n").encode())
        result["module_lines"][name] = len(source.splitlines())
        tree = ast.parse(source)
        sql = 0
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "execute"
            ):
                if node.args and isinstance(node.args[0], (ast.Constant, ast.JoinedStr)):
                    sql += 1
            if isinstance(node, ast.AsyncFunctionDef):
                result["async_transactions"] += transaction_calls(node)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if not node.name.startswith("_"):
                    result["public_return_annotations"]["total"] += 1
                    result["public_return_annotations"]["typed"] += node.returns is not None
                if node.name == "__init__" and any(a.arg == "runtime" for a in node.args.args):
                    result["runtime_dependencies"].append(f"{name}:{node.lineno}")
            if isinstance(node, ast.ClassDef) and node.name == "Services":
                result["untyped_service_fields"] = [
                    n.target.id
                    for n in node.body
                    if isinstance(n, ast.AnnAssign)
                    and isinstance(n.target, ast.Name)
                    and isinstance(n.annotation, ast.Name)
                    and n.annotation.id == "Any"
                ]
        if sql:
            result["sql_modules"][name] = sql
    result["backend_source_sha256"] = source_hash.hexdigest()
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--revision", help="Measure a committed revision without changing the working tree"
    )
    args = parser.parse_args()
    output = json.dumps(measure(args.revision), indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(output, encoding="utf-8")
    else:
        print(output, end="")


if __name__ == "__main__":
    main()
