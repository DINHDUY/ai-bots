"""Atomic per-bot tool selection and durable dispatch fences."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agentbot_control.approvals import Approvals
    from agentbot_control.event_store import EventStore
    from agentbot_control.run_streamer import RunStreamer
    from agentbot_control.store import Catalog

import json

from agentbot.tools import ToolUnavailable, legacy_selection
from agentbot.tools.catalog import ToolCatalog
from agentbot_tools.catalog import maintained_catalog
from fastapi import HTTPException, Request

from agentbot_control.event_store import identifier, packed, stamp


class ToolLibraries:
    def __init__(
        self,
        store: EventStore,
        *,
        approvals: Approvals,
        catalog: Catalog,
        streamers: dict[str, RunStreamer],
        binding_changed: Callable[[sqlite3.Connection, str], None],
        tool_catalog: ToolCatalog | None = None,
    ) -> None:
        self.store = store
        self.approvals = approvals
        self.catalog = catalog
        self.streamers = streamers
        self.binding_changed = binding_changed
        self.tool_catalog = tool_catalog or maintained_catalog()

    def ensure(self, bot):
        with self.store.transaction() as db:
            self.seed(db, bot)

    def seed(self, db, bot):
        if db.execute("SELECT 1 FROM bot_tool_config WHERE bot_id=?", (bot.id,)).fetchone():
            return
        selection = legacy_selection(bot.framework, self.tool_catalog.specs)
        for row in db.execute(
            "SELECT kind,resource_id FROM installations WHERE bot_id=?", (bot.id,)
        ):
            if bot.framework not in {"microsoft", "anthropic"}:
                continue
            selection.append(
                self.item(
                    "github.issues" if row["kind"] == "connector" else "skills.replay",
                    "github_issues" if row["kind"] == "connector" else "replay_skill",
                    row["resource_id"],
                )
            )
        self.replace(db, bot.id, selection, bot.owner_id, provenance="migration")

    @staticmethod
    def item(library, tool, resource=None):
        return {
            "library_id": library,
            "tool_id": tool,
            "version": "1.0.0",
            "configuration": {"resource_id": resource} if resource else {},
        }

    def rows(self, db, bid):
        return [
            self.unpack(row)
            for row in db.execute(
                "SELECT * FROM bot_tool_bindings WHERE bot_id=? AND enabled=1 ORDER BY library_id,tool_id,id",
                (bid,),
            )
        ]

    @staticmethod
    def unpack(row):
        result = dict(row)
        result["configuration"] = json.loads(result["configuration"])
        return result

    @staticmethod
    def selection(row):
        return {key: row[key] for key in ("library_id", "tool_id", "version", "configuration")}

    def validate(self, db, bid, framework, selection):
        if not isinstance(selection, list) or len(selection) > 64:
            raise HTTPException(422, "Select at most 64 tools.")
        normalized, seen = [], set()
        existing = {packed(self.selection(row)) for row in self.rows(db, bid)} if bid else set()
        for index, entry in enumerate(selection):
            if not isinstance(entry, dict) or set(entry) - {
                "library_id",
                "tool_id",
                "version",
                "configuration",
            }:
                raise HTTPException(422, f"tool_selection[{index}]: invalid fields")
            item = {**entry, "configuration": entry.get("configuration", {})}
            if not all(isinstance(item.get(k), str) for k in ("library_id", "tool_id", "version")):
                raise HTTPException(422, f"tool_selection[{index}]: IDs and version are required")
            config = item["configuration"]
            if not isinstance(config, dict) or len(packed(config)) > 8192:
                raise HTTPException(422, "Tool configuration must be a bounded object.")
            spec = self.tool_catalog.specs.get(f"{item['library_id']}/{item['tool_id']}")
            if not spec or spec.version != item["version"]:
                if packed(item) not in existing:
                    raise HTTPException(422, "Unknown tool or unavailable library version.")
            else:
                if framework not in spec.frameworks:
                    raise HTTPException(422, f"{spec.name} is unavailable for {framework}.")
                if set(config) - ({"resource_id"} if spec.resource else set()):
                    raise HTTPException(
                        422,
                        "Configuration accepts resource references, not credentials or arbitrary settings.",
                    )
                resource = config.get("resource_id")
                if resource is not None:
                    if not isinstance(resource, str) or not resource or len(resource) > 128:
                        raise HTTPException(422, "Invalid tool resource reference.")
                    if (
                        not bid or not self.resource_valid(db, bid, spec.resource, resource)
                    ) and packed(item) not in existing:
                        raise HTTPException(
                            422,
                            "Tool resource is unavailable for this bot. Configure its connection after creation.",
                        )
            key = (item["library_id"], item["tool_id"], packed(config))
            if key in seen:
                raise HTTPException(422, "Duplicate tool selection.")
            seen.add(key)
            normalized.append(item)
        selected = {f"{row['library_id']}/{row['tool_id']}" for row in normalized}
        for key in selected:
            spec = self.tool_catalog.specs.get(key)
            if spec and any(dep not in selected for dep in spec.dependencies):
                raise HTTPException(422, f"Select the declared dependencies for {spec.name}.")
        return normalized

    def resource_valid(self, db, bid, kind, rid):
        if kind == "connector":
            return bool(
                db.execute(
                    "SELECT 1 FROM connections WHERE id=? AND bot_id=? AND status!='revoked' AND secret IS NOT NULL",
                    (rid, bid),
                ).fetchone()
            )
        if kind == "skill":
            return bool(
                db.execute(
                    "SELECT 1 FROM skill_versions s JOIN bot_streams origin ON origin.bot_id=s.bot_id JOIN bot_streams target ON target.workspace_id=origin.workspace_id WHERE s.id=? AND target.bot_id=?",
                    (rid, bid),
                ).fetchone()
            )
        return False

    def replace(self, db, bid, selection, actor, expected=None, provenance="settings"):
        config = db.execute(
            "SELECT revision FROM bot_tool_config WHERE bot_id=?", (bid,)
        ).fetchone()
        revision = config[0] if config else 0
        if expected is not None and (type(expected) is not int or expected != revision):
            raise HTTPException(
                409,
                {
                    "message": "Tools changed in another window. Reload and review your selection.",
                    "tools_revision": revision,
                },
            )
        current = {packed(self.selection(row)): row for row in self.rows(db, bid)}
        wanted = {packed(item): item for item in selection}
        if config and current.keys() == wanted.keys():
            return
        removed = []
        for key, row in current.items():
            if key not in wanted:
                db.execute(
                    "UPDATE bot_tool_bindings SET enabled=0,revision=revision+1,updated_at=? WHERE id=?",
                    (stamp(), row["id"]),
                )
                removed.append(row["id"])
        for key, item in wanted.items():
            if key not in current:
                db.execute(
                    "INSERT INTO bot_tool_bindings VALUES (?,?,?,?,?,?,1,1,?,?)",
                    (
                        identifier("binding"),
                        bid,
                        item["library_id"],
                        item["version"],
                        item["tool_id"],
                        packed(item["configuration"]),
                        provenance,
                        stamp(),
                    ),
                )
        db.execute(
            "INSERT INTO bot_tool_config VALUES (?,?,1,?,?) ON CONFLICT(bot_id) DO UPDATE SET revision=excluded.revision,updated_by=excluded.updated_by,updated_at=excluded.updated_at",
            (bid, revision + 1, actor, stamp()),
        )
        for binding_id in removed:
            rows = db.execute(
                "SELECT p.* FROM approvals p JOIN actions a ON a.id=p.action_id WHERE a.tool_binding_id=? AND a.status IN ('awaiting_approval','authorized') AND p.status IN ('pending','approved')",
                (binding_id,),
            ).fetchall()
            for approval in rows:
                self.store._resolve(db, approval, "cancelled", actor)
        self.store._event(
            db,
            bid,
            "bot.tools.updated",
            {
                "tools_revision": revision + 1,
                "changed_by": actor,
                "selected_count": len(selection),
                "removed_binding_ids": removed,
            },
        )
        self.binding_changed(db, bid)

    def wake(self, bid):
        for streamer in list(self.streamers.values()):
            if streamer.bot_id != bid:
                continue
            for aid in streamer.pending_ids():
                row = self.approvals.get(aid)
                if row and row["status"] not in {"pending", "approved"}:
                    streamer.resolve(aid, False)

    def state(self, bid):
        with self.store.transaction() as db:
            config = db.execute(
                "SELECT revision FROM bot_tool_config WHERE bot_id=?", (bid,)
            ).fetchone()
            bindings = self.rows(db, bid)
            for binding in bindings:
                self.readiness(db, bid, binding)
        return {
            "tools_revision": config[0] if config else 0,
            "bindings": bindings,
            "tool_selection": [self.selection(row) for row in bindings],
            "selected_count": len(bindings),
            "ready_count": sum(b["ready"] for b in bindings),
        }

    def readiness(self, db, bid, binding, sandbox=None):
        spec = self.tool_catalog.specs.get(f"{binding['library_id']}/{binding['tool_id']}")
        reason = ""
        if spec is None or spec.version != binding["version"]:
            reason = "Unavailable library version"
        elif spec.resource:
            resource = binding["configuration"].get("resource_id")
            if not resource or not self.resource_valid(db, bid, spec.resource, resource):
                reason = "Needs setup: select a connection or taught task"
        if not reason and spec and spec.resource == "connector":
            connection = db.execute(
                "SELECT status FROM connections WHERE id=?",
                (binding["configuration"].get("resource_id"),),
            ).fetchone()
            if not connection or connection[0] != "connected":
                reason = "Needs setup: check or reconnect the repository connection"
        if (
            not reason
            and sandbox is not None
            and any(not callable(getattr(sandbox, method, None)) for method in spec.methods)
        ):
            reason = "Required computer service is unavailable"
        if (
            not reason
            and sandbox is not None
            and not spec.public(provider=getattr(sandbox, "provider", "docker"))["compatible"]
        ):
            reason = "Requires a different computer type"
        binding.update(
            ready=not reason,
            reason=reason,
            name=spec.name if spec else binding["tool_id"],
        )
        if spec and spec.library_id == "workspace.messaging" and not reason:
            entry = db.execute(
                "SELECT d.state,d.published,d.expires_at,c.enabled FROM workspace_bot_directory d JOIN workspace_channels c ON c.workspace_id=d.workspace_id WHERE d.bot_id=?",
                (bid,),
            ).fetchone()
            if (
                not entry
                or entry["state"] != "enabled"
                or not entry["published"]
                or not entry["enabled"]
                or (entry["expires_at"] and entry["expires_at"] <= stamp())
            ):
                binding.update(
                    ready=False,
                    reason="Join the workspace channel in Bot settings and enable workspace collaboration.",
                )
        if (
            sandbox is not None
            and getattr(sandbox, "communication_only", False)
            and spec
            and spec.requires_computer
        ):
            binding.update(ready=False, reason="Unavailable in a communication-only run")

    def pin(self, db, bot, rid):
        self.seed(db, bot)
        for binding in self.rows(db, bot.id):
            spec = self.tool_catalog.specs.get(f"{binding['library_id']}/{binding['tool_id']}")
            self.readiness(db, bot.id, binding)
            digest = spec.digest if spec and spec.version == binding["version"] else "unavailable"
            binding["manifest_digest"] = digest
            db.execute(
                "INSERT INTO run_tool_bindings VALUES (?,?,?,?,?)",
                (rid, binding["id"], binding["revision"], digest, packed(binding)),
            )

    def access(self, bid, rid, sandbox):
        with self.store.transaction() as db:
            bindings = [
                json.loads(row[0])
                for row in db.execute(
                    "SELECT snapshot FROM run_tool_bindings WHERE run_id=?", (rid,)
                )
            ]
            for binding in bindings:
                originally_ready = binding["ready"]
                self.readiness(db, bid, binding, sandbox)
                binding["ready"] = originally_ready and binding["ready"]

        def validate(binding):
            with self.store.transaction() as db:
                if not self.valid(
                    db,
                    bid,
                    rid,
                    binding["id"],
                    binding["revision"],
                    binding["manifest_digest"],
                ):
                    raise ToolUnavailable(
                        "Tool removed or changed; start a new task after reviewing Bot settings."
                    )

        return self.tool_catalog.access(bindings, validate=validate)

    def valid(self, db, bid, rid, binding_id, revision, digest):
        row = db.execute(
            "SELECT b.* FROM bot_tool_bindings b JOIN run_tool_bindings r ON r.binding_id=b.id AND r.run_id=? WHERE b.id=? AND b.bot_id=? AND b.enabled=1 AND b.revision=? AND r.binding_revision=b.revision AND r.manifest_digest=?",
            (rid, binding_id, bid, revision, digest),
        ).fetchone()
        if not row:
            return False
        binding = self.unpack(row)
        spec = self.tool_catalog.specs.get(f"{binding['library_id']}/{binding['tool_id']}")
        if not spec or spec.version != binding["version"] or spec.digest != digest:
            return False
        if spec.resource and not self.resource_valid(
            db, bid, spec.resource, binding["configuration"].get("resource_id")
        ):
            return False
        return True

    def resource_selection(self, db, bid, kind, rid, enabled):
        bot = self.catalog.get_bot_by_id_tx(db, bid)
        self.seed(db, bot)
        item = self.item(
            "github.issues" if kind == "connector" else "skills.replay",
            "github_issues" if kind == "connector" else "replay_skill",
            rid,
        )
        selection = [self.selection(row) for row in self.rows(db, bid)]
        selection = [row for row in selection if row != item]
        if enabled and bot.framework in {"microsoft", "anthropic"}:
            selection.append(item)
        self.replace(db, bid, selection, bot.owner_id, provenance="toolkit")


def register_tool_library_routes(app):
    service = app.state.runtime.tools

    @app.get("/api/tool-libraries")
    async def catalog(request: Request, framework: str | None = None, provider: str | None = None):
        app.state.runtime.workspaces.user(request)
        return {
            "libraries": [
                spec.public(framework, provider) for spec in service.tool_catalog.specs.values()
            ]
        }

    @app.get("/api/bots/{bot_id}/tools")
    async def selection(bot_id: str, request: Request):
        user = app.state.runtime.workspaces.user(request)
        bot = app.state.runtime.workspaces.bot(user.id, bot_id)
        app.state.runtime.ensure(bot)
        result = service.state(bot_id)
        result["editable"] = user.id == bot.owner_id
        with service.store.transaction() as db:
            result["resources"] = {
                "connector": [
                    dict(r)
                    for r in db.execute(
                        "SELECT id,repository AS name,status FROM connections WHERE bot_id=? AND status!='revoked'",
                        (bot_id,),
                    )
                ],
                "skill": [
                    dict(r)
                    for r in db.execute(
                        "SELECT s.id,s.name FROM skill_versions s JOIN bot_streams origin ON origin.bot_id=s.bot_id JOIN bot_streams target ON target.workspace_id=origin.workspace_id WHERE target.bot_id=?",
                        (bot_id,),
                    )
                ],
            }
        return result
