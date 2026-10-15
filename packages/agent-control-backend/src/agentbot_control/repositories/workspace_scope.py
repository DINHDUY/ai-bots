"""Explicit content ownership and deletion order for a workspace."""

import sqlite3

BOTS = "SELECT bot_id FROM bot_streams WHERE workspace_id=?"
RUNS = f"SELECT id FROM runs WHERE bot_id IN ({BOTS})"
THREADS = "SELECT id FROM channel_threads WHERE workspace_id=?"
DELIVERIES = f"SELECT id FROM channel_deliveries WHERE thread_id IN ({THREADS})"
ROUTINES = "SELECT id FROM routines WHERE workspace_id=?"
GROUPS = "SELECT id FROM groups WHERE workspace_id=?"
COMPUTERS = f"SELECT id FROM computer_sessions WHERE bot_id IN ({BOTS})"
BINDINGS = (
    "SELECT id FROM computer_provider_bindings WHERE workspace_id=? OR bot_id IN "
    "(SELECT bot_id FROM bot_streams WHERE workspace_id=?) OR profile_id IN "
    "(SELECT id FROM compute_profiles WHERE workspace_id=?)"
)

# Dependents precede parents. Bot-owned foreign-key cascades are audited separately.
CONTENT = (
    ("channel_dispatch_checks", f"delivery_id IN ({DELIVERIES})"),
    ("channel_deliveries", f"thread_id IN ({THREADS})"),
    ("channel_continuations", f"thread_id IN ({THREADS})"),
    ("channel_run_context", f"thread_id IN ({THREADS})"),
    ("channel_automation_roots", f"thread_id IN ({THREADS})"),
    ("channel_artifact_grants", "workspace_id=?"),
    ("channel_messages", "workspace_id=?"),
    ("channel_threads", "workspace_id=?"),
    ("workspace_bot_directory", "workspace_id=?"),
    ("channel_read_cursors", "workspace_id=?"),
    ("workspace_channel_events", "workspace_id=?"),
    ("channel_enrollment_policies", "workspace_id=?"),
    ("workspace_channels", "workspace_id=?"),
    ("routine_jobs", f"routine_id IN ({ROUTINES})"),
    ("webhook_deliveries", f"routine_id IN ({ROUTINES})"),
    ("routine_versions", f"routine_id IN ({ROUTINES})"),
    ("routines", "workspace_id=?"),
    ("handoffs", f"group_id IN ({GROUPS})"),
    ("group_messages", f"group_id IN ({GROUPS})"),
    ("group_members", f"group_id IN ({GROUPS})"),
    ("groups", "workspace_id=?"),
    ("search_index", f"bot_id IN ({BOTS})"),
    ("windows_bindings", f"bot_id IN ({BOTS})"),
    ("workspace_computer_settings", "workspace_id=?"),
    ("workspace_capture_retention", "workspace_id=?"),
    ("workspace_members", "workspace_id=?"),
)


def count(db: sqlite3.Connection, table: str, where: str, wid: str) -> int:
    return db.execute(f"SELECT COUNT(*) FROM {table} WHERE {where}", (wid,)).fetchone()[0]


def counts(db: sqlite3.Connection, wid: str) -> dict[str, int]:
    result = {table: count(db, table, where, wid) for table, where in CONTENT}
    for table in ("bots", "messages", "file_blobs", "uploads", "skill_versions", "connections"):
        result[table] = count(
            db, table, f"{'id' if table == 'bots' else 'bot_id'} IN ({BOTS})", wid
        )
    result["captures"] = count(db, "capture_storage", "workspace_id=? AND state!='removed'", wid)
    result["stored_bytes"] = (
        db.execute(
            f"SELECT COALESCE(SUM(size),0) FROM file_blobs WHERE bot_id IN ({BOTS})", (wid,)
        ).fetchone()[0]
        + db.execute(
            "SELECT COALESCE(SUM(size),0) FROM capture_storage WHERE workspace_id=? AND state!='removed'",
            (wid,),
        ).fetchone()[0]
    )
    return result
