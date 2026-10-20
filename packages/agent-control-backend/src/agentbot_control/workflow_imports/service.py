"""Preview and commit an entire imported workspace using one database worker."""

import hashlib
import sqlite3
from collections.abc import Callable

from agentbot.tools import legacy_selection
from anyio.to_thread import run_sync
from fastapi import HTTPException

from agentbot_control.channels import ChannelConfig, Channels, Participation
from agentbot_control.channels.membership import configure_tx
from agentbot_control.common import fingerprint, identifier
from agentbot_control.db import Database
from agentbot_control.repositories import workflow_imports as receipts
from agentbot_control.repositories.workspaces import attach_bot, create
from agentbot_control.schemas import Conflict
from agentbot_control.shared_computers.settings import initialize_shared
from agentbot_control.store import Catalog, CatalogError, _model_name
from agentbot_control.tool_libraries import ToolLibraries
from agentbot_control.workflow_imports.parser import issue, parse
from agentbot_control.workflow_imports.schemas import (
    PARSER_VERSION,
    ImportCommand,
    ImportDraft,
    ImportedBot,
    ImportPreview,
    ImportResult,
    ImportTool,
)


class WorkflowImports:
    def __init__(
        self,
        database: Database,
        catalog: Catalog,
        tools: ToolLibraries,
        channels: Channels,
        enabled: Callable[[], bool],
        known: Callable[[str], bool],
    ):
        self.database = database
        self.catalog = catalog
        self.tools = tools
        self.channels = channels
        self.enabled = enabled
        self.known = known

    def available(self) -> None:
        if not self.enabled() or not self.channels.enabled:
            raise HTTPException(
                409,
                "Workflow import requires workspace channels, tool libraries, and shared computers.",
            )

    def _resolve(
        self, db: sqlite3.Connection, owner: str, draft: ImportDraft, parsed: ImportPreview
    ) -> ImportPreview:
        self.available()
        result = parsed.model_copy(deep=True)
        manifests: list[str] = []
        for file in result.files:
            choice = file.runtime
            if choice.framework not in {"microsoft", "anthropic"} or not self.known(
                choice.framework
            ):
                file.errors.append(
                    issue(
                        "framework",
                        "framework",
                        "Choose Microsoft or Anthropic for a shared computer.",
                    )
                )
                continue
            try:
                receipts.credential(db, owner, choice.credential_id, choice.framework)
            except CatalogError as exc:
                file.errors.append(issue("credential_id", "credential", str(exc)))
            try:
                choice.model = _model_name(choice.model)
            except CatalogError as exc:
                file.errors.append(issue("model", "model", str(exc)))
            specs = self.tools.tool_catalog.specs
            selection = (
                legacy_selection(choice.framework, specs)
                if choice.tool_selection is None
                else [tool.model_dump() for tool in choice.tool_selection]
            )
            # Messaging is a required part of the reviewed import configuration.
            if not any(item["library_id"] == "workspace.messaging" for item in selection):
                selection.append(self.tools.item("workspace.messaging", "workspace_messaging"))
            try:
                selected = self.tools.validate(db, None, choice.framework, selection)
                for item in selected:
                    spec = specs[f"{item['library_id']}/{item['tool_id']}"]
                    if spec.resource or not spec.public(provider="docker")["compatible"]:
                        raise HTTPException(
                            422,
                            "Choose tools available on a new Docker computer; configure external resources after import.",
                        )
                    manifests.append(spec.digest)
                choice.tool_selection = [ImportTool.model_validate(item) for item in selected]
            except HTTPException as exc:
                file.errors.append(issue("tool_selection", "tools", str(exc.detail)))
        result.valid = not result.errors and not any(file.errors for file in result.files)
        result.preview_digest = fingerprint(
            {
                "parser": PARSER_VERSION,
                "draft": draft.model_dump(),
                "resolved": result.model_dump(exclude={"preview_digest"}),
                "manifests": manifests,
            }
        )
        return result

    async def preview(self, owner: str, draft: ImportDraft) -> ImportPreview:
        self.available()
        parsed = await run_sync(parse, draft)
        return await self.database.read(lambda db: self._resolve(db, owner, draft, parsed))

    async def receipt(self, owner: str, request_id: str) -> ImportResult:
        row = await self.database.read(lambda db: receipts.find(db, owner, request_id))
        if row is None:
            raise HTTPException(404, "Import receipt not found.")
        return ImportResult.model_validate_json(row["result"])

    @staticmethod
    def _previous(
        db: sqlite3.Connection, owner: str, command: ImportCommand, digest: str
    ) -> ImportResult | None:
        row = receipts.find(db, owner, command.request_id)
        if row is None:
            return None
        if row["fingerprint"] != digest:
            raise Conflict("This import request ID was already used with different arguments.")
        return ImportResult.model_validate_json(row["result"])

    async def commit(self, owner: str, command: ImportCommand) -> ImportResult:
        digest = fingerprint(command.model_dump(exclude={"request_id"}))
        previous = await self.database.read(lambda db: self._previous(db, owner, command, digest))
        if previous:
            return previous
        self.available()
        draft = ImportDraft.model_validate(
            command.model_dump(exclude={"request_id", "preview_digest"})
        )
        parsed = await run_sync(parse, draft)
        return await self.database.run(
            lambda db: self._commit(db, owner, command, draft, parsed, digest)
        )

    def _commit(
        self,
        db: sqlite3.Connection,
        owner: str,
        command: ImportCommand,
        draft: ImportDraft,
        parsed: ImportPreview,
        digest: str,
    ) -> ImportResult:
        previous = self._previous(db, owner, command, digest)
        if previous:
            return previous
        preview = self._resolve(db, owner, draft, parsed)
        if not preview.valid:
            raise HTTPException(
                422,
                {
                    "message": "Correct the import errors and preview again.",
                    "errors": [error.model_dump() for error in preview.errors],
                    "files": [
                        {
                            "file_id": file.file_id,
                            "errors": [error.model_dump() for error in file.errors],
                        }
                        for file in preview.files
                    ],
                },
            )
        if command.preview_digest != preview.preview_digest:
            raise Conflict(
                "Import preview changed. Review a fresh preview before importing.",
                code="preview_changed",
            )
        wid = identifier("workspace")
        create(db, wid, owner, preview.workspace_name)
        initialize_shared(db, wid, owner)
        configure_tx(self.channels, db, owner, wid, ChannelConfig(revision=0, enabled=True))
        imported = []
        for source, file in zip(draft.files, preview.files, strict=True):
            choice = file.runtime
            bot = self.catalog.create_bot(
                owner,
                file.name,
                choice.framework,
                file.instructions,
                choice.credential_id,
                choice.model,
                _db=db,
                preserve_instructions=True,
            )
            attach_bot(db, wid, bot.id)
            self.tools.replace(
                db,
                bot.id,
                [tool.model_dump() for tool in choice.tool_selection or []],
                owner,
                provenance="workflow_import",
            )
            self.channels.enroll(
                db,
                bot.id,
                owner,
                Participation(
                    revision=0,
                    enabled=True,
                    purpose=file.purpose,
                ),
            )
            imported.append(
                ImportedBot(
                    file_id=file.file_id,
                    filename=file.filename,
                    bot_id=bot.id,
                    name=bot.name,
                    source_hash=hashlib.sha256(source.content.encode("utf-8")).hexdigest(),
                    body_hash=hashlib.sha256(file.instructions.encode("utf-8")).hexdigest(),
                )
            )
        result = ImportResult(
            request_id=command.request_id,
            workspace_id=wid,
            workspace_name=preview.workspace_name,
            bots=imported,
        )
        receipts.save(
            db, owner, command.request_id, digest, PARSER_VERSION, wid, result.model_dump_json()
        )
        return result
