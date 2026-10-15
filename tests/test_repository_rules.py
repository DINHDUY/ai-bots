import subprocess

import pytest

from scripts.check_python_size import (
    Measurement,
    active_lines,
    maintained_files,
    measure,
    size_violation,
)
from scripts.repository_rules import source_violations


@pytest.mark.parametrize("count, fails", [(449, False), (450, True), (500, True), (501, True)])
def test_enforces_proactive_and_hard_limits(count, fails):
    assert bool(size_violation(Measurement("example.py", count, count))) is fails


def test_counts_code_without_comments_or_real_docstrings():
    source = '"""Module\ndocumentation"""\n# comment\n\nclass Example:\n    """Class docs"""\n    def call(self):\n        """Function docs"""\n        return 1  # inline\n'
    assert active_lines(source) == 3
    assert active_lines('"docs"; value = 1\n') == 1
    assert active_lines('value = "a string"\n"not a docstring"\n') == 2


def test_multiline_executable_strings_and_continuations_count():
    assert active_lines('query = """SELECT\n\n# SQL text\nvalue"""\n') == 3
    assert active_lines("value = (\n    1 +\n    2\n)\n") == 4
    assert active_lines("@decorator\ndef function():\n    return 1\n") == 3


@pytest.mark.parametrize(
    "source, expected",
    [
        ("", 0),
        ('# comment\r\n"docs"\r\n', 0),
        ('("first"\n "second")\nvalue = 1\n', 1),
        ('class Café: "docs"; value = 1\n', 1),
    ],
)
def test_docstring_forms_do_not_hide_executable_lines(source, expected):
    assert active_lines(source) == expected


def test_crlf_and_declared_encoding(tmp_path):
    source = tmp_path / "encoded.py"
    source.write_bytes(b'# coding: latin-1\r\n"caf\xe9"\r\nvalue = 1\r\n')
    assert measure(tmp_path, [source]) == [Measurement("encoded.py", 1, 3)]


def test_git_inventory_includes_new_nested_files_and_excludes_ignored(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / ".gitignore").write_text("ignored/\n", encoding="utf-8")
    for name in ["tracked.py", "domain/new.py", "ignored/dependency.py"]:
        path = tmp_path / name
        path.parent.mkdir(exist_ok=True)
        path.write_text("x = 1\n", encoding="utf-8")
    subprocess.run(["git", "add", "tracked.py"], cwd=tmp_path, check=True)
    files = maintained_files(tmp_path)
    assert tmp_path / "tracked.py" in files
    assert tmp_path / "domain/new.py" in files
    assert tmp_path / "ignored/dependency.py" not in files
    (tmp_path / "tracked.py").unlink()
    assert tmp_path / "tracked.py" not in maintained_files(tmp_path)


@pytest.mark.parametrize(
    "name, source",
    [
        ("src/domain/test_feature.py", ""),
        ("src/domain/feature_test.py", ""),
        ("src/domain/conftest.py", ""),
        ("src/test/helpers.ts", ""),
        ("src/feature.test.tsx", ""),
        ("src/feature.py", "from package.tests import helper\n"),
        ("src/feature.py", "from package import tests\n"),
        ("src/feature.ts", 'import { helper } from "../tests/support";'),
    ],
)
def test_production_cannot_contain_or_import_tests(tmp_path, name, source):
    path = tmp_path / name
    path.parent.mkdir(parents=True)
    path.write_text(source, encoding="utf-8")
    assert source_violations(tmp_path, [path])


def test_separate_tests_and_ordinary_source_are_allowed(tmp_path):
    files = []
    for name in ["tests/test_feature.py", "tests/support.py", "src/domain/models.py"]:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("", encoding="utf-8")
        files.append(path)
    assert source_violations(tmp_path, files) == []


def test_source_cannot_import_a_flat_test_helper(tmp_path):
    helper = tmp_path / "tests" / "fakes.py"
    helper.parent.mkdir()
    helper.write_text("VALUE = 1\n", encoding="utf-8")
    source = tmp_path / "src" / "feature.py"
    source.parent.mkdir()
    source.write_text("from fakes import VALUE\n", encoding="utf-8")
    assert source_violations(tmp_path, [helper, source])
