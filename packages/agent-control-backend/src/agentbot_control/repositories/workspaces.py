"""workspaces, workspace_members, and bot_streams."""

import sqlite3


def create(db: sqlite3.Connection, workspace_id: str, user_id: str, name: str) -> None:
    db.execute(
        "INSERT INTO workspaces(id,owner_id,name) VALUES (?,?,?)", (workspace_id, user_id, name)
    )
    db.execute("INSERT INTO workspace_members VALUES (?,?,'owner')", (workspace_id, user_id))


def attach_bot(db: sqlite3.Connection, workspace_id: str, bot_id: str) -> None:
    db.execute("INSERT INTO bot_streams(bot_id,workspace_id) VALUES (?,?)", (bot_id, workspace_id))


def personal(db, user_id):
    wid = "personal_" + user_id
    db.execute(
        "INSERT OR IGNORE INTO workspaces(id,owner_id,name) VALUES (?,?,?)",
        (wid, user_id, "Personal workspace"),
    )
    db.execute(
        "INSERT OR IGNORE INTO workspace_members VALUES (?,?, 'owner')",
        (wid, user_id),
    )
    return wid
