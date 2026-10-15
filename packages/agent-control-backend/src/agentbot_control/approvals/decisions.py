from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

from agentbot_control.autopilot import read_state
from agentbot_control.event_store import (
    fingerprint,
    identifier,
    packed,
    protected,
    sanitized,
    stamp,
)
from agentbot_control.policies import scope_description, scope_for


class Approvals:
    def __init__(self, store, policies):
        self.store, self.policies = store, policies

    def valid_context(self, db, row):
        run = db.execute("SELECT * FROM runs WHERE id=?", (row["run_id"],)).fetchone()
        computer = (
            db.execute(
                "SELECT * FROM computer_sessions WHERE id=?",
                (run["session_id"],),
            ).fetchone()
            if run and run["session_id"]
            else None
        )
        tools = self.store.hooks.admission
        tool_valid = True
        if tools:
            action = db.execute("SELECT * FROM actions WHERE id=?", (row["action_id"],)).fetchone()
            tool_valid = bool(
                action
                and tools.valid(
                    db,
                    row["bot_id"],
                    row["run_id"],
                    action["tool_binding_id"],
                    action["tool_binding_revision"],
                    action["tool_manifest_digest"],
                )
            )
        return bool(
            tool_valid
            and run
            and (
                self.store.hooks.channels is None
                or self.store.hooks.channels.valid_run(db, row["run_id"])
            )
            and not db.execute(
                "SELECT 1 FROM channel_continuations WHERE source_run_id=? AND state IN ('waiting','queued','resumed')",
                (row["run_id"],),
            ).fetchone()
            and computer
            and run["status"] in {"running", "awaiting_approval"}
            and computer["id"] == run["session_id"]
            and computer["generation"] == row["generation"]
            and computer["status"] == "running"
        )

    def register(
        self,
        bot_id,
        rid,
        frame,
        timeout,
        secrets=(),
        *,
        arguments=None,
        context=None,
        step_id=None,
        requires_approval=True,
        allowed_policy_id="*",
        tool_binding=None,
    ):
        arguments = arguments if arguments is not None else {"legacy_detail": frame["detail"]}
        context = context or {}
        tools = self.store.hooks.admission
        if tools and tool_binding is None:
            tool_binding = tools.access(bot_id, rid, None).operation(frame["action"], arguments)
        tool_binding = tool_binding or {}
        expiry = (datetime.now(UTC) + timedelta(seconds=timeout)).isoformat()
        action_id, digest = identifier("action"), fingerprint(arguments)
        clean = sanitized(frame, secrets)
        if frame["action"] in {"file_write", "file_edit"} and not protected(
            str(arguments.get("path", ""))
        ):
            clean["detail"] = sanitized(frame["detail"] + "\n" + packed(arguments), secrets)
        scope = scope_for(frame["action"], arguments, context)
        description = (
            sanitized(scope_description(frame["action"], scope), secrets) if scope else None
        )
        with self.store.transaction() as db:
            run = db.execute("SELECT * FROM runs WHERE id=? AND bot_id=?", (rid, bot_id)).fetchone()
            computer = db.execute(
                "SELECT * FROM computer_sessions WHERE id=?", (run["session_id"],)
            ).fetchone()
            db.execute(
                "INSERT INTO actions(id,run_id,name,argument_digest,status,session_id,generation,arguments_sealed,context,step_id,tool_binding_id,tool_binding_revision,tool_manifest_digest) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    action_id,
                    rid,
                    frame["action"],
                    digest,
                    "awaiting_approval",
                    computer["id"],
                    computer["generation"],
                    self.policies.seal(arguments),
                    packed(context),
                    step_id,
                    tool_binding.get("id"),
                    tool_binding.get("revision"),
                    tool_binding.get("manifest_digest"),
                ),
            )
            db.execute(
                "INSERT INTO approvals(id,bot_id,run_id,action_id,action,detail,status,expires_at,created_at,generation,argument_digest,policy_scope) VALUES (?,?,?,?,?,?,'pending',?,?,?,?,?)",
                (
                    frame["approval_id"],
                    bot_id,
                    rid,
                    action_id,
                    frame["action"],
                    clean["detail"],
                    expiry,
                    stamp(),
                    computer["generation"],
                    digest,
                    description,
                ),
            )
            row = db.execute(
                "SELECT * FROM approvals WHERE id=?", (frame["approval_id"],)
            ).fetchone()
            if not self.valid_context(db, row):
                self.store._resolve(db, row, "cancelled")
            elif requires_approval and (autopilot := read_state(db, bot_id))["enabled"]:
                self.store._resolve(
                    db,
                    row,
                    "approved",
                    autopilot["changed_by"],
                    decision_source="autopilot",
                    autopilot_revision=autopilot["revision"],
                )
            else:
                policy = (
                    self.policies.match(db, bot_id, frame["action"], arguments, context)
                    if requires_approval
                    else None
                )
                if policy and allowed_policy_id not in {"*", policy["id"]}:
                    policy = None
                if policy or not requires_approval:
                    if policy:
                        db.execute(
                            "UPDATE approvals SET policy_id=?,policy_version=? WHERE id=?",
                            (policy["id"], policy["version"], row["id"]),
                        )
                        row = db.execute(
                            "SELECT * FROM approvals WHERE id=?", (row["id"],)
                        ).fetchone()
                    self.store._resolve(
                        db,
                        row,
                        "approved",
                        f"policy:{policy['id']}" if policy else "system:observation",
                    )
                else:
                    db.execute(
                        "UPDATE runs SET status='awaiting_approval',updated_at=? WHERE id=? AND status='running'",
                        (stamp(), rid),
                    )
                    self.store._event(
                        db,
                        bot_id,
                        "approval.required",
                        {
                            **clean,
                            "revision": 1,
                            "expires_at": expiry,
                            "argument_digest": digest,
                            "policy_scope": description,
                            "step_id": step_id,
                        },
                        rid,
                        action_id,
                    )
            return dict(db.execute("SELECT * FROM approvals WHERE id=?", (row["id"],)).fetchone())

    def get(self, approval_id):
        with self.store.transaction() as db:
            return dict(db.execute("SELECT * FROM approvals WHERE id=?", (approval_id,)).fetchone())

    def pending_action(self, bot_id, aid):
        with self.store.transaction() as db:
            row = db.execute(
                "SELECT a.* FROM actions a JOIN approvals p ON p.action_id=a.id WHERE p.bot_id=? AND p.id=? AND p.status='pending'",
                (bot_id, aid),
            ).fetchone()
            return dict(row) if row else None

    def invalidate(self, aid):
        with self.store.transaction() as db:
            row = db.execute(
                "SELECT * FROM approvals WHERE id=? AND status='pending'", (aid,)
            ).fetchone()
            if row:
                self.store._resolve(db, row, "cancelled")

    def expire(self, approval_id, *, force=False):
        with self.store.transaction() as db:
            row = db.execute("SELECT * FROM approvals WHERE id=?", (approval_id,)).fetchone()
            if (
                row
                and row["status"] == "pending"
                and (force or row["expires_at"] <= stamp() or not self.valid_context(db, row))
            ):
                self.store._resolve(
                    db,
                    row,
                    "expired" if force or row["expires_at"] <= stamp() else "cancelled",
                )
            return (
                dict(db.execute("SELECT * FROM approvals WHERE id=?", (approval_id,)).fetchone())
                if row
                else None
            )

    def decision(self, bot_id, aid, request_id, decision, revision, user_id):
        body = dict(operation="decision", approval_id=aid, decision=decision, revision=revision)
        with self.store.transaction() as db:
            previous = self.store._receipt(db, bot_id, request_id, body)
            if previous:
                return previous
            row = db.execute(
                "SELECT * FROM approvals WHERE id=? AND bot_id=?", (aid, bot_id)
            ).fetchone()
            if not row:
                raise KeyError("Approval not found.")
            wanted = "approved" if decision == "approve" else "denied"
            if row["status"] == "pending":
                if row["expires_at"] <= stamp():
                    self.store._resolve(db, row, "expired")
                elif not self.valid_context(db, row):
                    self.store._resolve(db, row, "cancelled")
                elif row["revision"] == revision:
                    self.store._resolve(db, row, wanted, user_id)
            current = db.execute("SELECT * FROM approvals WHERE id=?", (aid,)).fetchone()
            response = dict(
                approval_id=aid,
                run_id=current["run_id"],
                action_id=current["action_id"],
                status=current["status"],
                revision=current["revision"],
                decided_by=current["decided_by"],
                accepted=current["status"] == wanted,
            )
            self.store._save_receipt(db, bot_id, request_id, body, response)
            return response

    def claim(self, aid, arguments, context):
        """CAS and publish action.started in the same transaction as authorization recheck."""
        with self.store.transaction() as db:
            row = db.execute("SELECT * FROM approvals WHERE id=?", (aid,)).fetchone()
            action = db.execute("SELECT * FROM actions WHERE id=?", (row["action_id"],)).fetchone()
            valid = (
                row["status"] == "approved"
                and self.valid_context(db, row)
                and action["argument_digest"] == fingerprint(arguments)
                and json.loads(action["context"]) == context
            )
            if row["policy_id"]:
                policy = self.policies.match(db, row["bot_id"], action["name"], arguments, context)
                valid = (
                    valid
                    and policy is not None
                    and policy["id"] == row["policy_id"]
                    and policy["version"] == row["policy_version"]
                )
            if row["decision_source"] == "autopilot":
                mode = read_state(db, row["bot_id"])
                valid = valid and mode["enabled"] and mode["revision"] == row["autopilot_revision"]
            if not valid or action["status"] != "authorized":
                return False
            changed = db.execute(
                "UPDATE actions SET status='executing',started_at=? WHERE id=? AND status='authorized'",
                (stamp(), action["id"]),
            ).rowcount
            if changed:
                self.store._event(
                    db,
                    row["bot_id"],
                    "action.started",
                    {
                        "operation": action["name"],
                        "tool_binding_id": action["tool_binding_id"],
                        "tool_binding_revision": action["tool_binding_revision"],
                        "tool_manifest_digest": action["tool_manifest_digest"],
                        "detail": row["detail"],
                        "approval_id": aid,
                        "step_id": action["step_id"],
                        "policy_id": row["policy_id"],
                        "policy_version": row["policy_version"],
                        "decision_source": row["decision_source"],
                        "autopilot_revision": row["autopilot_revision"],
                        "decided_by": row["decided_by"],
                    },
                    row["run_id"],
                    action["id"],
                )
            return bool(changed)

    def result(self, approval, result, secrets):
        with self.store.transaction() as db:
            data = sanitized(result.public(), secrets)
            changed = db.execute(
                "UPDATE actions SET status=?,result=?,ended_at=? WHERE id=? AND result IS NULL",
                (
                    "unknown"
                    if data.get("outcome_unknown")
                    else "completed"
                    if result.ok
                    else "cancelled"
                    if result.cancelled
                    else "failed",
                    packed(data),
                    stamp(),
                    approval["action_id"],
                ),
            ).rowcount
            if changed:
                current = db.execute(
                    "SELECT decision_source,autopilot_revision,decided_by FROM approvals WHERE id=?",
                    (approval["id"],),
                ).fetchone()
                self.store._event(
                    db,
                    approval["bot_id"],
                    "action.completed" if result.ok else "action.failed",
                    {
                        **data,
                        **dict(current),
                        "operation": approval["action"],
                        "approval_id": approval["id"],
                    },
                    approval["run_id"],
                    approval["action_id"],
                )
