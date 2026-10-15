"""Test placement and production dependency checks, shared by the repository gate."""

from __future__ import annotations

import ast
import re
import tokenize
from pathlib import Path

TEST_DIRECTORIES = {"test", "tests", "e2e", "test_support", "testing"}


def test_name(name: str) -> bool:
    return (
        name.startswith("test_")
        or name.endswith("_test.py")
        or ".test." in name
        or ".spec." in name
    )


def test_dependency(module: str) -> bool:
    parts = re.split(r"[./\\]", module)
    return any(part in TEST_DIRECTORIES or part.startswith("test_") for part in parts)


def source_violations(root: Path, files: list[Path]) -> list[str]:
    errors = []
    test_modules = {
        path.stem
        for path in files
        if path.suffix == ".py"
        and TEST_DIRECTORIES.intersection(path.relative_to(root).parts)
        and path.stem != "__init__"
    }
    for path in files:
        relative = path.relative_to(root)
        if "src" not in relative.parts or path.suffix not in {".py", ".ts", ".tsx", ".js", ".jsx"}:
            continue
        below_source = relative.parts[relative.parts.index("src") + 1 :]
        if (
            any(part in TEST_DIRECTORIES for part in below_source)
            or test_name(path.name)
            or path.name == "conftest.py"
        ):
            errors.append(
                f"{relative.as_posix()}: tests and support must be outside production source"
            )
            continue
        if path.suffix == ".py":
            with tokenize.open(path) as stream:
                tree = ast.parse(stream.read())
            for node in ast.walk(tree):
                modules = []
                if isinstance(node, ast.Import):
                    modules = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom):
                    modules = [node.module or ""]
                    modules += [f"{node.module or ''}.{alias.name}" for alias in node.names]
                if any(
                    test_dependency(module) or module in test_modules or module == "pytest"
                    for module in modules
                ):
                    errors.append(
                        f"{relative.as_posix()}:{node.lineno}: production imports test support"
                    )
        else:
            source = path.read_text(encoding="utf-8")
            imports = re.findall(
                r"""(?:from\s*|import\s*\(?|require\s*\()\s*["']([^"']+)["']""", source
            )
            if any(
                test_dependency(module)
                or ".test" in module
                or ".spec" in module
                or module == "vitest"
                or module.startswith("@testing-library/")
                for module in imports
            ):
                errors.append(f"{relative.as_posix()}: production imports test support")
    return errors
