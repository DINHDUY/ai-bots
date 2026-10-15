"""Admission and settlement for external file writers."""

from agentbot_control.common import stamp
from agentbot_control.schemas import Conflict


def start(db, token, bot_id):
    if not db.execute(
        "SELECT 1 FROM bot_streams b JOIN workspaces w ON w.id=b.workspace_id WHERE b.bot_id=? AND w.deleted_at IS NULL",
        (bot_id,),
    ).fetchone():
        raise Conflict("Workspace unavailable.", code="workspace_deleted")
    db.execute(
        "INSERT INTO workspace_file_writers(id,bot_id,created_at) VALUES (?,?,?)",
        (token, bot_id, stamp()),
    )


def finish(db, token):
    db.execute(
        "UPDATE workspace_file_writers SET state='cleanup_pending' WHERE id=? AND staging_name IS NOT NULL",
        (token,),
    )
    db.execute("DELETE FROM workspace_file_writers WHERE id=? AND staging_name IS NULL", (token,))


def staging(db, token, filename):
    db.execute("UPDATE workspace_file_writers SET staging_name=? WHERE id=?", (filename, token))
