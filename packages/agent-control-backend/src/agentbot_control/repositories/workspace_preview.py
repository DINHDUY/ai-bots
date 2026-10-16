"""Deletion impact and quiescence checks on one database snapshot."""

import sqlite3

from fastapi import HTTPException

from agentbot_control.common import fingerprint
from agentbot_control.repositories.workspace_scope import (
    BINDINGS,
    BOTS,
    GROUPS,
    ROUTINES,
    RUNS,
    THREADS,
    counts,
)
from agentbot_control.schemas import Conflict
from agentbot_control.workspace_deletions.schemas import (
    Blocker,
    BotSummary,
    DeletionPreview,
    RetainedComputer,
)


def owner_workspace(db: sqlite3.Connection, owner: str, wid: str) -> sqlite3.Row:
    row = db.execute("SELECT * FROM workspaces WHERE id=? AND owner_id=?", (wid, owner)).fetchone()
    if row is None:
        raise HTTPException(404, "Workspace unavailable.")
    if row["deleted_at"]:
        previous = db.execute(
            "SELECT request_id FROM workspace_deletions WHERE workspace_id=?", (wid,)
        ).fetchone()
        raise Conflict(
            "Workspace was already deleted. Recover request " + (previous[0] if previous else wid),
            code="workspace_deleted",
        )
    return row


def preview(db: sqlite3.Connection, owner: str, wid: str) -> DeletionPreview:
    workspace = owner_workspace(db, owner, wid)
    blockers = []
    url = f"/workspace?workspace={wid}"

    def block(code: str, message: str, target: str = url) -> None:
        blockers.append(Blocker(code=code, message=message, url=target))

    if wid == "personal_" + workspace["owner_id"]:
        block("workspace_protected", "The Personal workspace cannot be deleted.")
    bots = db.execute(
        f"SELECT id,name,owner_id,updated_at FROM bots WHERE id IN ({BOTS}) ORDER BY id", (wid,)
    ).fetchall()
    if any(bot["owner_id"] != owner for bot in bots):
        block("ownership_conflict", "This workspace contains bots owned by another user.")
    checks = (
        (
            "runs",
            f"bot_id IN ({BOTS}) AND status IN ('preparing','running','awaiting_approval','stopping')",
            "runs_active",
            "Finish or stop active bot tasks.",
            url,
        ),
        (
            "computer_sessions",
            "(workspace_id=? OR bot_id IN (SELECT bot_id FROM bot_streams WHERE workspace_id=?)) AND status!='closed'",
            "computers_active",
            "Close all per-bot and shared computers, including hibernated or failed sessions.",
            url + "&tab=computer",
        ),
        (
            "control_leases",
            f"bot_id IN ({BOTS}) AND status NOT IN ('released','expired')",
            "control_active",
            "Release human control and complete input reconciliation.",
            url + "&tab=computer",
        ),
        (
            "workspace_file_writers",
            f"bot_id IN ({BOTS})",
            "transfers_active",
            "Wait for file transfers to finish.",
            url,
        ),
        (
            "capture_storage",
            "workspace_id=? AND state='reserved'",
            "transfers_active",
            "Wait for screenshot storage to finish.",
            url,
        ),
        (
            "lifecycle_operations",
            "(workspace_id=? OR bot_id IN (SELECT bot_id FROM bot_streams WHERE workspace_id=?)) AND status NOT IN ('completed','closed','failed')",
            "recovery_required",
            "Resolve pending computer operations.",
            url + "&tab=computer",
        ),
        (
            "actions",
            f"run_id IN ({RUNS}) AND status IN ('started','executing','outcome_unknown','unknown')",
            "recovery_required",
            "Reconcile actions whose effects are uncertain.",
            url,
        ),
        (
            "routine_jobs",
            f"routine_id IN ({ROUTINES}) AND state IN ('running','starting','claimed','admitted')",
            "runs_active",
            "Wait for claimed routine jobs to settle.",
            url + "&tab=routines",
        ),
        (
            "handoffs",
            f"group_id IN ({GROUPS}) AND state IN ('running','starting','claimed','admitted')",
            "runs_active",
            "Wait for handoffs to settle.",
            url + "&tab=groups",
        ),
        (
            "channel_deliveries",
            f"thread_id IN ({THREADS}) AND state IN ('admitted','running')",
            "runs_active",
            "Wait for admitted channel deliveries to settle.",
            f"/channel?workspace={wid}",
        ),
        (
            "macos_bindings",
            f"bot_id IN ({BOTS}) AND active=1",
            "recovery_required",
            "Disconnect the workspace Mac sessions.",
            url + "&tab=computer",
        ),
        (
            "windows_bindings",
            f"bot_id IN ({BOTS}) AND active=1",
            "recovery_required",
            "Disconnect the workspace's Windows sessions.",
            url + "&tab=computer",
        ),
    )
    for table, where, code, message, target in checks:
        if db.execute(
            f"SELECT 1 FROM {table} WHERE {where} LIMIT 1", (wid,) * where.count("?")
        ).fetchone():
            block(code, message, target)
    bindings = db.execute(
        f"SELECT * FROM computer_provider_bindings WHERE id IN ({BINDINGS}) ORDER BY id",
        (wid, wid, wid),
    ).fetchall()
    retained = []
    for row in bindings:
        retained.append(
            RetainedComputer(
                binding_id=row["id"],
                provider=row["provider"],
                resource_id=row["resource_id"],
                cleanup_state=row["cleanup_state"],
                url=f"/api/workspaces/{wid}/compute-inventory",
            )
        )
        unsettled = db.execute(
            "SELECT 1 FROM cloud_operation_state WHERE binding_id=? AND phase NOT IN ('completed','failed')",
            (row["id"],),
        ).fetchone()
        if (
            row["owner_id"] != owner
            or row["active"]
            or row["cleanup_state"] not in ("retained_stopped", "deleted")
            or unsettled
        ):
            block(
                "recovery_required",
                "Retire and reconcile Azure computers before deleting this workspace.",
                url + "&tab=computer",
            )
    result = DeletionPreview(
        workspace_id=wid,
        workspace_name=workspace["name"],
        bots=[BotSummary(id=b["id"], name=b["name"]) for b in bots],
        counts=counts(db, wid),
        blockers=blockers,
        retained=retained,
        preview_digest="",
    )
    revisions = {}
    for label, query in (
        (
            "members",
            "SELECT user_id,role FROM workspace_members WHERE workspace_id=? ORDER BY user_id",
        ),
        (
            "streams",
            "SELECT bot_id,seq,captures_revision FROM bot_streams WHERE workspace_id=? ORDER BY bot_id",
        ),
        ("groups", "SELECT id,revision FROM groups WHERE workspace_id=? ORDER BY id"),
        ("routines", "SELECT id,version,enabled FROM routines WHERE workspace_id=? ORDER BY id"),
        (
            "channel",
            "SELECT revision,seq,directory_revision FROM workspace_channels WHERE workspace_id=?",
        ),
        (
            "computers",
            "SELECT id,generation,status FROM computer_sessions WHERE workspace_id=? OR bot_id IN (SELECT bot_id FROM bot_streams WHERE workspace_id=?) ORDER BY id",
        ),
    ):
        revisions[label] = [tuple(r) for r in db.execute(query, (wid,) * query.count("?"))]
    result.preview_digest = fingerprint(
        {
            "preview": result.model_dump(exclude={"preview_digest", "blockers"}),
            "bots": [tuple(b) for b in bots],
            "revisions": revisions,
        }
    )
    return result
