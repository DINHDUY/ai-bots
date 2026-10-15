"""Keep the deletion table inventory exhaustive across future migrations."""

import re
from pathlib import Path

from agentbot_control.db import Database


def test_every_catalog_table_has_a_documented_deletion_disposition(tmp_path):
    root = Path(__file__).resolve().parents[3]
    audit = (root / "docs/028-workspace-deletion-audit.md").read_text(encoding="utf-8")
    tables = []
    for line in audit.split("## Producers", 1)[0].splitlines():
        if line.startswith("| ") and "`" in line:
            tables.extend(re.findall(r"`([a-z_]+)`", line))
    database = Database(tmp_path / "audit.sqlite")
    try:
        actual = {
            row[0]
            for row in database.connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' AND name NOT LIKE 'search_index_%'"
            )
        }
        assert len(tables) == len(set(tables)), "Each table must have one disposition"
        assert set(tables) == actual
        assert not database.connection.execute("PRAGMA foreign_key_check").fetchall()
    finally:
        database.close()
