"""approvals and the actions row they release."""

from agentbot_control.common import stamp


def resolve(db, row, status, user_id, decision_source, autopilot_revision):
    changed = db.execute(
        "UPDATE approvals SET status=?,revision=revision+1,decided_by=?,decision_source=?,autopilot_revision=? WHERE id=? AND status='pending'",
        (status, user_id, decision_source, autopilot_revision, row["id"]),
    ).rowcount
    if not changed:
        return False
    db.execute(
        "UPDATE actions SET status=? WHERE id=?",
        ("authorized" if status == "approved" else status, row["action_id"]),
    )
    db.execute(
        "UPDATE runs SET status='running',updated_at=? WHERE id=? AND status='awaiting_approval'",
        (stamp(), row["run_id"]),
    )
    return True
