"""Exact, typed authorization scopes. No shell parsing or pattern grants."""

import hashlib
import json
from datetime import UTC, datetime, timedelta
from urllib.parse import urlsplit

from agentbot.sandbox.paths import resolve_workspace_path, validate_http_url

from agentbot_control.event_store import identifier, packed, sanitized, stamp
from agentbot_control.schemas import Conflict


def origin(url):
    validate_http_url(url)
    parts = urlsplit(url)
    if parts.username or parts.password:
        raise ValueError("Browser rules cannot contain URL credentials.")
    port = parts.port
    host = parts.hostname.lower()
    if ":" in host:
        host = f"[{host}]"
    return f"{parts.scheme.lower()}://{host}" + (
        f":{port}" if port and port != (443 if parts.scheme == "https" else 80) else ""
    )


def scope_for(operation, arguments, context):
    """Return only supported scopes; unsupported context always requires a person."""
    if (
        operation == "connector.github"
        and set(arguments)
        == {
            "connection_id",
            "connection_version",
            "repository",
            "operation",
            "title",
            "text",
        }
        and arguments["operation"] in {"list_issues", "create_issue"}
    ):
        return dict(arguments)
    if (
        operation == "bash"
        and set(arguments) == {"command"}
        and context.get("workspace_revision")
    ):
        return dict(
            command=arguments["command"],
            workspace_revision=context["workspace_revision"],
        )
    if (
        operation == "file_write"
        and set(arguments) == {"path", "content"}
        and context.get("file_revision")
    ):
        return dict(
            path=resolve_workspace_path(arguments["path"]),
            content_sha256=hashlib.sha256(arguments["content"].encode()).hexdigest(),
            expected_revision=context["file_revision"],
        )
    if (
        operation == "file_edit"
        and arguments.get("command") in {"create", "insert", "str_replace"}
        and context.get("file_revision")
    ):
        return dict(
            path=resolve_workspace_path(arguments["path"]),
            arguments_sha256=hashlib.sha256(packed(arguments).encode()).hexdigest(),
            expected_revision=context["file_revision"],
        )
    if (
        operation == "open_browser"
        and set(arguments) == {"url"}
        and context.get("browser_scoped")
    ):
        return dict(origin=origin(arguments["url"]))
    return None


class Policies:
    def __init__(self, store, catalog):
        self.store, self.catalog = store, catalog

    def seal(self, value):
        return self.catalog.seal(packed(value).encode())

    def open(self, value):
        return json.loads(self.catalog.unseal(value))

    def public(self, row):
        return {
            key: row[key]
            for key in (
                "id",
                "bot_id",
                "operation",
                "summary",
                "expires_at",
                "created_at",
                "created_by",
                "version",
                "revoked_at",
                "revoked_by",
            )
        } | {
            "status": "revoked"
            if row["revoked_at"]
            else "expired"
            if row["expires_at"] <= stamp()
            else "active"
        }

    def list(self, bot_id):
        with self.store.transaction() as db:
            return [
                self.public(row)
                for row in db.execute(
                    "SELECT * FROM approval_policies WHERE bot_id=? ORDER BY created_at DESC",
                    (bot_id,),
                )
            ]

    def create(self, bot_id, user_id, command):
        """Derive immutable typed constraints from a reviewed server action.

        The caller cannot substitute arguments using a redacted UI summary.
        Creating a rule does not decide the outstanding request.
        """
        body = {"operation": "create_policy", **command.model_dump()}
        with self.store.transaction() as db:
            previous = self.store._receipt(db, bot_id, command.request_id, body)
            if previous:
                return previous
            row = db.execute(
                "SELECT a.*, p.status AS approval_status, p.detail FROM actions a JOIN approvals p ON p.action_id=a.id WHERE p.id=? AND p.bot_id=?",
                (command.approval_id, bot_id),
            ).fetchone()
            if not row:
                raise KeyError("Approval not found.")
            if (
                row["approval_status"] not in {"pending", "approved"}
                or not row["arguments_sealed"]
            ):
                raise Conflict(
                    "A rule requires a current or previously approved action."
                )
            scope = scope_for(
                row["name"],
                self.open(row["arguments_sealed"]),
                json.loads(row["context"]),
            )
            if not scope:
                raise Conflict("This action has no supported persistent scope.")
            summary = row["detail"] + "\n" + scope_description(row["name"], scope)
            policy_id = identifier("policy")
            expiry = (
                datetime.now(UTC) + timedelta(seconds=command.ttl_seconds)
            ).isoformat()
            db.execute(
                "INSERT INTO approval_policies(id,bot_id,operation,constraints_sealed,summary,expires_at,created_at,created_by) VALUES (?,?,?,?,?,?,?,?)",
                (
                    policy_id,
                    bot_id,
                    row["name"],
                    self.seal(scope),
                    summary,
                    expiry,
                    stamp(),
                    user_id,
                ),
            )
            result = self.public(
                db.execute(
                    "SELECT * FROM approval_policies WHERE id=?", (policy_id,)
                ).fetchone()
            )
            self.store._event(db, bot_id, "policy.created", result)
            self.store._save_receipt(db, bot_id, command.request_id, body, result)
            return result

    def revoke(self, bot_id, policy_id, user_id, command):
        body = dict(
            operation="revoke_policy", policy_id=policy_id, **command.model_dump()
        )
        with self.store.transaction() as db:
            previous = self.store._receipt(db, bot_id, command.request_id, body)
            if previous:
                return previous
            row = db.execute(
                "SELECT * FROM approval_policies WHERE bot_id=? AND id=?",
                (bot_id, policy_id),
            ).fetchone()
            if not row:
                raise KeyError("Policy not found.")
            if not row["revoked_at"]:
                db.execute(
                    "UPDATE approval_policies SET revoked_at=?,revoked_by=?,version=version+1 WHERE id=?",
                    (stamp(), user_id, policy_id),
                )
            result = self.public(
                db.execute(
                    "SELECT * FROM approval_policies WHERE id=?", (policy_id,)
                ).fetchone()
            )
            self.store._event(db, bot_id, "policy.revoked", result)
            self.store._save_receipt(db, bot_id, command.request_id, body, result)
            return result

    def match(self, db, bot_id, operation, arguments, context):
        scope = scope_for(operation, arguments, context)
        if scope is None:
            return None
        for row in db.execute(
            "SELECT * FROM approval_policies WHERE bot_id=? AND operation=? AND revoked_at IS NULL AND expires_at>? ORDER BY created_at,id",
            (bot_id, operation, stamp()),
        ):
            if self.open(row["constraints_sealed"]) == scope:
                return row
        return None


def scope_description(operation, scope):
    if operation == "connector.github":
        return (
            "Exact GitHub "
            + scope["operation"]
            + " on "
            + scope["repository"]
            + "; pinned connection version and reviewed issue content."
        )
    if operation == "bash":
        return (
            "Exact shell text; workspace revision "
            + scope["workspace_revision"]
            + ". Any workspace change requires fresh approval."
        )
    if operation in {"file_write", "file_edit"}:
        return (
            "Exact file mutation at "
            + scope["path"]
            + "; expected revision "
            + scope["expected_revision"]
            + "."
        )
    return (
        "Open URLs on origin "
        + sanitized(scope["origin"])
        + ". Redirects to other origins require approval."
    )
