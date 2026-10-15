"""computer_sessions, computer_health, and retention flags."""

from agentbot_control.common import packed, stamp


def save_health(db, session_id, observed_at, report, *, only_if_changed=False):
    sql = "INSERT INTO computer_health VALUES (?,?,?) ON CONFLICT(session_id) DO UPDATE SET observed_at=excluded.observed_at,report=excluded.report"
    if only_if_changed:
        sql += " WHERE computer_health.observed_at!=excluded.observed_at"
    return db.execute(sql, (session_id, observed_at, packed(report))).rowcount


def mark_closing(db, session_id):
    db.execute(
        "UPDATE computer_sessions SET status='closing',updated_at=? WHERE id=?",
        (stamp(), session_id),
    )


def clear_pause(db, session_id):
    db.execute("UPDATE computer_control SET paused=0 WHERE session_id=?", (session_id,))


def warn_retention(db, session_id):
    db.execute(
        "INSERT INTO computer_retention(session_id,warned) VALUES (?,1) ON CONFLICT(session_id) DO UPDATE SET warned=1",
        (session_id,),
    )


def legacy_setting(db, session_id):
    return db.execute(
        "SELECT value FROM runtime_settings WHERE key=?",
        ("legacy:" + session_id,),
    ).fetchone()
