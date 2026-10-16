"""macOS device persistence; called on the shared database worker."""

from __future__ import annotations

import hashlib
import json
import secrets
from datetime import UTC, datetime, timedelta

from fastapi import HTTPException

from agentbot_control.common import identifier, stamp
from agentbot_control.repositories import receipts, runs
from agentbot_control.schemas import Conflict


def token_hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def snapshot(db):
    configs = db.execute(
        "SELECT c.*,d.owner_id,d.revoked_at FROM macos_compute_config c JOIN macos_devices d ON d.id=c.device_id"
    ).fetchall()
    bindings = db.execute("SELECT * FROM macos_bindings").fetchall()
    return {r["bot_id"]: dict(r) for r in configs}, {r["session_id"]: dict(r) for r in bindings}


def list_devices(db, owner):
    return [
        dict(r)
        for r in db.execute(
            "SELECT id,name,revoked_at FROM macos_devices WHERE owner_id=? AND revoked_at IS NULL",
            (owner,),
        )
    ]


def authenticate(db, token):
    row = db.execute(
        "SELECT * FROM macos_devices WHERE token_hash=? AND revoked_at IS NULL",
        (token_hash(token),),
    ).fetchone()
    return dict(row) if row else None


def enroll(db, owner, request_id):
    if db.execute(
        "SELECT 1 FROM macos_enrollments WHERE owner_id=? AND request_id=?", (owner, request_id)
    ).fetchone():
        raise Conflict("Enrollment already issued; create a new request if its code was lost")
    code = secrets.token_urlsafe(32)
    expires = (datetime.now(UTC) + timedelta(minutes=10)).isoformat()
    db.execute(
        "INSERT INTO macos_enrollments VALUES (?,?,?,?,NULL,?)",
        (identifier("mac_enroll"), owner, token_hash(code), expires, request_id),
    )
    return {"code": code, "expires_at": expires}


def complete(db, code, name):
    row = db.execute(
        "SELECT * FROM macos_enrollments WHERE secret_hash=? AND consumed_at IS NULL AND expires_at>?",
        (token_hash(code), stamp()),
    ).fetchone()
    if not row:
        raise HTTPException(403, "Enrollment expired or already used")
    token, did = secrets.token_urlsafe(48), identifier("mac")
    db.execute("UPDATE macos_enrollments SET consumed_at=? WHERE id=?", (stamp(), row["id"]))
    db.execute(
        "INSERT INTO macos_devices VALUES (?,?,?,?,?,NULL)",
        (did, row["owner_id"], name, token_hash(token), stamp()),
    )
    return {"device_id": did, "token": token}


def select(db, owner, bot_id, command):
    fingerprint = {"operation": "macos.select", **command.model_dump()}
    old = receipts.find(db, bot_id, command.request_id)
    if old:
        from agentbot_control.common import fingerprint as hashed

        if old["fingerprint"] != hashed(fingerprint):
            raise Conflict("Request ID reused with changed parameters")
        return json.loads(old["response"])
    bot = db.execute("SELECT owner_id,framework FROM bots WHERE id=?", (bot_id,)).fetchone()
    if not bot or bot[0] != owner or bot[1] != "open_interface":
        raise HTTPException(404, "Mac bot not found")
    if (
        runs.active(db, bot_id)
        or db.execute(
            "SELECT 1 FROM computer_sessions WHERE bot_id=? AND status!='closed'", (bot_id,)
        ).fetchone()
    ):
        raise Conflict("Disconnect the current computer before changing its binding")
    if not db.execute(
        "SELECT 1 FROM macos_devices WHERE id=? AND owner_id=? AND revoked_at IS NULL",
        (command.device_id, owner),
    ).fetchone():
        raise HTTPException(404, "Mac not found")
    row = db.execute(
        "SELECT revision FROM macos_compute_config WHERE bot_id=?", (bot_id,)
    ).fetchone()
    revision = row[0] if row else 0
    if revision != command.expected_revision:
        raise Conflict("Computer configuration changed")
    db.execute(
        "INSERT INTO macos_compute_config VALUES (?,?,?) ON CONFLICT(bot_id) DO UPDATE SET device_id=excluded.device_id,revision=excluded.revision",
        (bot_id, command.device_id, revision + 1),
    )
    result = {"provider": "macos_local", "device_id": command.device_id, "revision": revision + 1}
    receipts.save(db, bot_id, command.request_id, fingerprint, result)
    return result


def claim_binding(db, bot_id, sid, generation):
    row = db.execute(
        "SELECT c.device_id FROM macos_compute_config c JOIN macos_devices d ON d.id=c.device_id JOIN bots b ON b.id=c.bot_id WHERE c.bot_id=? AND d.revoked_at IS NULL AND b.framework='open_interface' AND b.owner_id=d.owner_id",
        (bot_id,),
    ).fetchone()
    if not row:
        raise Conflict("Select a paired Mac first")
    other = db.execute(
        "SELECT session_id FROM macos_bindings WHERE device_id=? AND active=1 AND session_id!=?",
        (row[0], sid),
    ).fetchone()
    if other:
        raise Conflict("Another bot is connected to this Mac; disconnect it first")
    db.execute(
        "INSERT INTO macos_bindings VALUES (?,?,?,?,1) ON CONFLICT(session_id) DO UPDATE SET active=1",
        (sid, bot_id, row[0], generation),
    )
    return dict(db.execute("SELECT * FROM macos_bindings WHERE session_id=?", (sid,)).fetchone())


def close_binding(db, sid):
    db.execute("UPDATE macos_bindings SET active=0 WHERE session_id=?", (sid,))


def revoke(db, owner, did):
    if not db.execute(
        "SELECT 1 FROM macos_devices WHERE id=? AND owner_id=?", (did, owner)
    ).fetchone():
        raise HTTPException(404, "Mac not found")
    db.execute(
        "UPDATE macos_devices SET revoked_at=COALESCE(revoked_at,?) WHERE id=?", (stamp(), did)
    )


def pause(db, did, reason, emit):
    rows = db.execute(
        "SELECT * FROM macos_bindings WHERE device_id=? AND active=1", (did,)
    ).fetchall()
    result = []
    for row in rows:
        db.execute(
            "INSERT INTO computer_control(session_id,paused) VALUES (?,1) ON CONFLICT(session_id) DO UPDATE SET paused=1,fence=fence+1",
            (row["session_id"],),
        )
        emit(db, row["bot_id"], "computer.local_paused", {"reason": reason})
        run = runs.active(db, row["bot_id"])
        if run:
            result.append((row["bot_id"], run["id"]))
    return result


def executing(db, action_id, sid, action):
    row = db.execute(
        "SELECT a.*,r.id AS current_run,r.status AS run_status FROM actions a JOIN runs r ON r.id=a.run_id WHERE a.id=? AND r.session_id=?",
        (action_id, sid),
    ).fetchone()
    if not row or row["status"] != "executing" or row["run_status"] != "running":
        raise Conflict("No current execution claim for this action")
    binding = db.execute(
        "SELECT b.generation,s.generation AS session_generation,s.status,c.paused,d.revoked_at FROM macos_bindings b JOIN computer_sessions s ON s.id=b.session_id JOIN macos_devices d ON d.id=b.device_id LEFT JOIN computer_control c ON c.session_id=b.session_id WHERE b.session_id=? AND b.active=1",
        (sid,),
    ).fetchone()
    if (
        not binding
        or binding["revoked_at"]
        or binding["paused"]
        or binding["generation"] != binding["session_generation"]
        or binding["status"] != "running"
    ):
        raise Conflict("Mac binding changed before dispatch")
    from agentbot_control.common import fingerprint

    if row["argument_digest"] != fingerprint(action):
        raise Conflict("Action arguments changed after approval")
    return row["current_run"]
