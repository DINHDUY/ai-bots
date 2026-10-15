"""Creation-time workspace computer configuration; no external lifecycle effects."""

import sqlite3

from agentbot_control.common import stamp


def initialize_shared_docker(db: sqlite3.Connection, workspace_id: str, owner: str) -> None:
    db.execute(
        "INSERT INTO workspace_computer_settings "
        "(workspace_id,mode,provider,ownership,revision,updated_by,updated_at) "
        "VALUES (?,'shared','docker','attached',1,?,?)",
        (workspace_id, owner, stamp()),
    )
