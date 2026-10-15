"""Owner-controlled automatic decisions, serialized with action dispatch in SQLite."""

from fastapi import HTTPException, Request
from pydantic import Field, StrictBool

from agentbot_control.common import stamp
from agentbot_control.schemas import Command, Conflict


class SetAutopilot(Command):
    enabled: StrictBool
    expected_revision: int = Field(ge=0)


def read_state(db, bot_id):
    row = db.execute("SELECT * FROM bot_autopilot WHERE bot_id=?", (bot_id,)).fetchone()
    return (
        {**dict(row), "enabled": bool(row["enabled"])}
        if row
        else {
            "bot_id": bot_id,
            "enabled": False,
            "revision": 0,
            "changed_by": None,
            "changed_at": None,
        }
    )


class Autopilot:
    def __init__(self, store, workspaces, approvals, streamers):
        self.store = store
        self.workspaces = workspaces
        self.approvals = approvals
        self.streamers = streamers

    def state(self, bot_id):
        with self.store.transaction() as db:
            return read_state(db, bot_id)

    def change(self, user_id, bot_id, command):
        self.workspaces.bot(user_id, bot_id, "owner")
        body = {
            "operation": "autopilot",
            "bot_id": bot_id,
            "principal": user_id,
            **command.model_dump(),
        }
        with self.store.transaction() as db:
            owner = db.execute(
                "SELECT b.owner_id FROM bots b JOIN bot_streams s ON s.bot_id=b.id JOIN workspace_members m ON m.workspace_id=s.workspace_id AND m.user_id=? WHERE b.id=?",
                (user_id, bot_id),
            ).fetchone()
            if not owner or owner[0] != user_id:
                raise HTTPException(403, "Only the bot owner can change Autopilot.")
            previous = self.store._receipt(db, bot_id, command.request_id, body)
            if previous:
                return previous
            state = read_state(db, bot_id)
            if state["revision"] != command.expected_revision:
                raise Conflict(
                    "Autopilot changed in another tab. Reload before updating."
                )
            resolved, invalidated = [], []
            if state["enabled"] != command.enabled:
                state = {
                    "bot_id": bot_id,
                    "enabled": command.enabled,
                    "revision": state["revision"] + 1,
                    "changed_by": user_id,
                    "changed_at": stamp(),
                }
                db.execute(
                    "INSERT INTO bot_autopilot VALUES (?,?,?,?,?) ON CONFLICT(bot_id) DO UPDATE SET enabled=excluded.enabled,revision=excluded.revision,changed_by=excluded.changed_by,changed_at=excluded.changed_at",
                    (
                        bot_id,
                        int(state["enabled"]),
                        state["revision"],
                        user_id,
                        state["changed_at"],
                    ),
                )
                self.store._event(db, bot_id, "bot.autopilot.changed", state)
                if state["enabled"]:
                    for row in db.execute(
                        "SELECT * FROM approvals WHERE bot_id=? AND status='pending'",
                        (bot_id,),
                    ).fetchall():
                        if row["expires_at"] <= stamp():
                            status = "expired"
                        elif not self.approvals.valid_context(db, row):
                            status = "cancelled"
                        else:
                            status = "approved"
                        self.store._resolve(
                            db,
                            row,
                            status,
                            user_id if status == "approved" else None,
                            decision_source="autopilot"
                            if status == "approved"
                            else None,
                            autopilot_revision=state["revision"]
                            if status == "approved"
                            else None,
                        )
                        resolved.append(row["id"])
                else:
                    for row in db.execute(
                        "SELECT p.* FROM approvals p JOIN actions a ON a.id=p.action_id WHERE p.bot_id=? AND p.status='approved' AND p.decision_source='autopilot' AND a.status='authorized'",
                        (bot_id,),
                    ).fetchall():
                        db.execute(
                            "UPDATE approvals SET status='cancelled',revision=revision+1 WHERE id=?",
                            (row["id"],),
                        )
                        db.execute(
                            "UPDATE actions SET status='cancelled' WHERE id=? AND status='authorized'",
                            (row["action_id"],),
                        )
                        self.store._event(
                            db,
                            bot_id,
                            "approval.resolved",
                            {
                                "approval_id": row["id"],
                                "status": "cancelled",
                                "revision": row["revision"] + 1,
                                "decided_by": row["decided_by"],
                                "decision_source": "autopilot",
                                "autopilot_revision": row["autopilot_revision"],
                                "reason": "Autopilot disabled before execution",
                                "revoked_by": user_id,
                            },
                            row["run_id"],
                            row["action_id"],
                        )
                        invalidated.append(row["id"])
            result = {
                **state,
                "resolved_approval_ids": resolved,
                "invalidated_approval_ids": invalidated,
            }
            self.store._save_receipt(db, bot_id, command.request_id, body, result)
        # The action holds its lock while waiting. Wake only after the decision commits.
        for aid in resolved + invalidated:
            row = self.approvals.get(aid)
            streamer = self.streamers.get(row["run_id"])
            if streamer:
                streamer.resolve(aid, row["status"] == "approved")
        return result


def register_autopilot_routes(app):
    from agentbot_control.authorization import request_bot
    from agentbot_control.transport import body

    service = app.state.runtime.autopilot

    @app.get("/api/bots/{bot_id}/autopilot")
    async def get(bot_id: str, request: Request):
        user, bot = request_bot(request, bot_id)
        return {**service.state(bot_id), "can_manage": user.id == bot.owner_id}

    @app.post("/api/bots/{bot_id}/autopilot")
    async def set_mode(bot_id: str, request: Request):
        user, _ = request_bot(request, bot_id)
        command = await body(request, SetAutopilot)
        return {**service.change(user.id, bot_id, command), "can_manage": True}
