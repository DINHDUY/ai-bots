"""Resolve a bot to its own computer or the workspace shared computer."""

from __future__ import annotations

from agentbot_control.common import stamp
from agentbot_control.schemas import ACTIVE_RUNS

_ACTIVE = ",".join("'" + status + "'" for status in ACTIVE_RUNS)


def settings_row(db, workspace_id):
    row = db.execute(
        "SELECT * FROM workspace_computer_settings WHERE workspace_id=?",
        (workspace_id,),
    ).fetchone()
    if not row:
        return {
            "workspace_id": workspace_id,
            "mode": "per_bot",
            "provider": "docker",
            "profile_id": None,
            "ownership": "attached",
            "revision": 0,
            "updated_by": None,
            "updated_at": None,
        }
    return dict(row)


def workspace_of(db, bot_id):
    row = db.execute("SELECT workspace_id FROM bot_streams WHERE bot_id=?", (bot_id,)).fetchone()
    return row[0] if row else None


def eligible(db, bot_id) -> bool:
    bot = db.execute("SELECT framework FROM bots WHERE id=?", (bot_id,)).fetchone()
    if not bot or bot[0] == "ufo":
        return False
    return not db.execute("SELECT 1 FROM bot_compute_config WHERE bot_id=?", (bot_id,)).fetchone()


def uses_shared(db, bot_id):
    wid = workspace_of(db, bot_id)
    if not wid or not eligible(db, bot_id):
        return None
    settings = settings_row(db, wid)
    return settings if settings["mode"] == "shared" else None


def computer_for(db, bot_id):
    shared = uses_shared(db, bot_id)
    if shared:
        row = db.execute(
            "SELECT * FROM computer_sessions WHERE workspace_id=? ORDER BY generation DESC LIMIT 1",
            (shared["workspace_id"],),
        ).fetchone()
        return dict(row) if row else None
    row = db.execute(
        "SELECT * FROM computer_sessions WHERE bot_id=? ORDER BY generation DESC LIMIT 1",
        (bot_id,),
    ).fetchone()
    return dict(row) if row else None


def open_computer(db, workspace_id):
    row = db.execute(
        "SELECT * FROM computer_sessions WHERE workspace_id=? AND status!='closed' ORDER BY generation DESC LIMIT 1",
        (workspace_id,),
    ).fetchone()
    return dict(row) if row else None


def open_bot_computer(db, bot_id):
    row = db.execute(
        "SELECT * FROM computer_sessions WHERE bot_id=? AND status!='closed'",
        (bot_id,),
    ).fetchone()
    return dict(row) if row else None


def attached_bot_ids(db, workspace_id):
    return [
        row[0]
        for row in db.execute(
            "SELECT b.id FROM bots b JOIN bot_streams s ON s.bot_id=b.id "
            "WHERE s.workspace_id=? AND b.framework!='ufo' "
            "AND NOT EXISTS (SELECT 1 FROM bot_compute_config c WHERE c.bot_id=b.id)",
            (workspace_id,),
        ).fetchall()
    ]


def present(computer, db=None):
    if not computer:
        return None
    data = dict(computer)
    shared = bool(data.get("workspace_id")) and not data.get("bot_id")
    data["scope"] = "workspace" if shared else "bot"
    if shared and db is not None:
        data["attached_bot_ids"] = attached_bot_ids(db, data["workspace_id"])
    elif data.get("bot_id"):
        data["attached_bot_ids"] = [data["bot_id"]]
    else:
        data["attached_bot_ids"] = []
    return data


def blocking(db, workspace_id) -> bool:
    return bool(
        db.execute(
            "SELECT 1 FROM computer_sessions c WHERE c.status!='closed' AND ("
            "c.workspace_id=? OR c.bot_id IN ("
            "SELECT b.id FROM bots b JOIN bot_streams s ON s.bot_id=b.id "
            "WHERE s.workspace_id=? AND b.framework!='ufo' "
            "AND NOT EXISTS (SELECT 1 FROM bot_compute_config cfg WHERE cfg.bot_id=b.id)"
            ")) LIMIT 1",
            (workspace_id, workspace_id),
        ).fetchone()
    )


def session_busy(db, sid) -> bool:
    return bool(
        db.execute(
            f"SELECT 1 FROM runs WHERE session_id=? AND status IN ({_ACTIVE})",
            (sid,),
        ).fetchone()
        or db.execute(
            "SELECT 1 FROM control_leases WHERE session_id=? AND status IN ('active','releasing')",
            (sid,),
        ).fetchone()
    )


def active_runs(db, sid):
    return [
        dict(row)
        for row in db.execute(
            f"SELECT id, bot_id FROM runs WHERE session_id=? AND status IN ({_ACTIVE})",
            (sid,),
        ).fetchall()
    ]


def shared_session(db, sid):
    row = db.execute(
        "SELECT bot_id, workspace_id FROM computer_sessions WHERE id=?", (sid,)
    ).fetchone()
    return row if row and row["workspace_id"] and not row["bot_id"] else None


def emit(store, db, bot_id, kind, data, session_id=None):
    row = shared_session(db, session_id) if session_id else None
    if row:
        payload = {**data, "scope": "workspace", "workspace_id": row["workspace_id"]}
        for target in attached_bot_ids(db, row["workspace_id"]):
            store._event(db, target, kind, payload)
        return
    if bot_id:
        store._event(db, bot_id, kind, data)


def emit_workspace(store, db, workspace_id, kind, data):
    payload = {**data, "scope": "workspace", "workspace_id": workspace_id}
    for target in attached_bot_ids(db, workspace_id):
        store._event(db, target, kind, payload)


def set_status(store, bot_id, sid, status):
    with store.transaction() as db:
        row = db.execute("SELECT * FROM computer_sessions WHERE id=?", (sid,)).fetchone()
        if not row:
            return
        if row["bot_id"]:
            if bot_id and row["bot_id"] != bot_id:
                return
            db.execute(
                "UPDATE computer_sessions SET status=?,updated_at=? WHERE id=? AND bot_id=?",
                (status, stamp(), sid, row["bot_id"]),
            )
            store._event(db, row["bot_id"], "session." + status, {"status": status, "scope": "bot"})
            return
        db.execute(
            "UPDATE computer_sessions SET status=?,updated_at=? WHERE id=?",
            (status, stamp(), sid),
        )
        emit(store, db, None, "session." + status, {"status": status}, sid)


def bot_blocked(store, bot_id) -> bool:
    with store.transaction() as db:
        return uses_shared(db, bot_id) is not None


def lease_row(db, bot_id):
    computer = computer_for(db, bot_id)
    columns = (
        "id,session_id,generation,user_id,client_id,surface,surface_id,"
        "viewport_revision,fence,expires_at,status,last_sequence"
    )
    if computer and computer.get("workspace_id") and not computer.get("bot_id"):
        return db.execute(
            f"SELECT {columns} FROM control_leases WHERE session_id=? AND status IN ('active','releasing')",
            (computer["id"],),
        ).fetchone()
    return db.execute(
        f"SELECT {columns} FROM control_leases WHERE bot_id=? AND status IN ('active','releasing')",
        (bot_id,),
    ).fetchone()


def paused(db, bot_id) -> bool:
    computer = computer_for(db, bot_id)
    if not computer or computer["status"] == "closed":
        return False
    row = db.execute(
        "SELECT paused FROM computer_control WHERE session_id=?", (computer["id"],)
    ).fetchone()
    return bool(row and row[0])


def takeover_runs(store, bot_id, sid):
    with store.transaction() as db:
        if shared_session(db, sid):
            return active_runs(db, sid)
    run = store.active(bot_id)
    return [run] if run else []


def still_active(store, bot_id, sid) -> bool:
    with store.transaction() as db:
        if shared_session(db, sid):
            return bool(active_runs(db, sid))
    return bool(store.active(bot_id))


def primary_bot(store, workspace_id):
    if not workspace_id:
        return None
    with store.transaction() as db:
        ids = attached_bot_ids(db, workspace_id)
    return ids[0] if ids else None


def warn_idle(store, computer, seconds_remaining):
    with store.transaction() as db:
        db.execute(
            "INSERT INTO computer_retention(session_id,warned) VALUES (?,1) "
            "ON CONFLICT(session_id) DO UPDATE SET warned=1",
            (computer["id"],),
        )
        emit_workspace(
            store,
            db,
            computer["workspace_id"],
            "lifecycle.idle_warning",
            {"seconds_remaining": seconds_remaining},
        )


def session_busy_store(store, sid) -> bool:
    with store.transaction() as db:
        return session_busy(db, sid)


def ensure_runnable(store, cloud, bot):
    from agentbot_control.schemas import Conflict

    with store.transaction() as db:
        shared = uses_shared(db, bot.id)
        if not shared:
            return
        computer = open_computer(db, shared["workspace_id"])
        provider = shared["provider"]
        workspace_id = shared["workspace_id"]
    if provider.startswith("azure_"):
        from agentbot_control.shared_computers.cloud import binding_report

        binding = cloud.binding(workspace_id=workspace_id)
        if not binding_report(cloud, binding)["compatible"]:
            raise Conflict(
                "Shared cloud computer is not ready. Attach or start it from workspace settings.",
                code="workspace_computer",
            )
        return
    if not computer or computer["status"] != "running":
        raise Conflict(
            "Create the shared workspace computer before running a bot.",
            code="workspace_computer",
        )
