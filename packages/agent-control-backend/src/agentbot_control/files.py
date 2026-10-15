"""Revision-bound file access and explicit owned attachments."""

import asyncio
import base64
import hashlib
import mimetypes
import tempfile
from pathlib import Path

from agentbot.interfaces import FileServiceSandbox, SandboxError
from agentbot.sandbox.paths import WorkspacePathError, resolve_workspace_path
from fastapi import HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import ValidationError

from agentbot_control.authorization import request_bot
from agentbot_control.blob_store import BlobStore
from agentbot_control.event_store import identifier, protected, stamp
from agentbot_control.file_transfers import FileTransfers
from agentbot_control.schemas import Command, Conflict


class Files:
    def __init__(self, store, computers, action_locks, mutex, control):
        self.store = store
        self.computers = computers
        self.action_locks = action_locks
        self.mutex = mutex
        self.control = control
        self.blobs = BlobStore(self.store)
        self.transfers = FileTransfers(store.database)

    async def existing(self, bot_id, sid):
        computer, sandbox = await self.computers.existing(bot_id, sid)
        if not isinstance(sandbox, FileServiceSandbox):
            raise Conflict("File service unavailable.")
        return computer, sandbox

    async def snapshot(self, bot_id, sid, path, revision, run_id=None):
        async with self.transfers.writer(bot_id):
            return await self._snapshot(bot_id, sid, path, revision, run_id)

    async def _snapshot(self, bot_id, sid, path, revision, run_id=None):
        _, sandbox = await self.existing(bot_id, sid)
        lock = self.action_locks.setdefault(sid, asyncio.Lock())
        if lock.locked():
            raise Conflict("Wait for the current action to finish before downloading live files.")
        async with lock:
            meta = await sandbox.files("snapshot", path=path, revision=revision)
            blob_id = None
            try:
                blob_id = self.blobs.reserve(
                    bot_id,
                    sid,
                    meta["path"],
                    meta["revision"],
                    meta["size"],
                    meta["mime"],
                )
                digest, offset = hashlib.sha256(), 0
                with (self.blobs.directory / blob_id).open("xb") as out:
                    while offset < meta["size"]:
                        result = await sandbox.files("read", token=meta["token"], offset=offset)
                        raw = base64.b64decode(result["data"], validate=True)
                        if not raw or len(raw) > 65536 or offset + len(raw) > meta["size"]:
                            raise Conflict("Invalid file transfer chunk.")
                        out.write(raw)
                        digest.update(raw)
                        offset += len(raw)
                if digest.hexdigest() != meta["revision"]:
                    raise Conflict("Snapshot bytes do not match their revision.")
                with self.store.transaction() as db:
                    db.execute(
                        "INSERT INTO search_index VALUES (?,?,'file',?,'')",
                        (blob_id, bot_id, meta["path"]),
                    )
                    self.store._event(
                        db,
                        bot_id,
                        "artifact.retained",
                        {
                            "artifact_id": blob_id,
                            "path": meta["path"],
                            "revision": meta["revision"],
                            "size": meta["size"],
                        },
                        run_id,
                    )
                return blob_id
            except BaseException:
                if blob_id:
                    self.blobs.discard(blob_id)
                raise
            finally:
                await asyncio.shield(sandbox.files("drop", token=meta["token"]))

    async def upload(self, bot_id, sid, user_id, command, upload, path, expected):
        async with self.transfers.writer(bot_id) as transfer_id:
            return await self._upload(
                bot_id, sid, user_id, command, upload, path, expected, transfer_id
            )

    async def _upload(self, bot_id, sid, user_id, command, upload, path, expected, transfer_id):
        path = resolve_workspace_path(path)
        if protected(path):
            raise HTTPException(403, "Protected files expose metadata only.")
        computer, sandbox = await self.existing(bot_id, sid)
        temporary = tempfile.NamedTemporaryFile(
            dir=self.blobs.directory, delete=False, prefix=f"staging-{transfer_id}-"
        )
        temp_path = Path(temporary.name)
        token, blob_id = None, None
        try:
            digest, size = hashlib.sha256(), 0
            await self.transfers.staging(transfer_id, temp_path.name)
            with temporary:
                while raw := await upload.read(65536):
                    size += len(raw)
                    if size > 64 * 1024 * 1024:
                        raise HTTPException(413, "Upload exceeds 64 MiB.")
                    digest.update(raw)
                    await self.store.database.offload(lambda: temporary.write(raw))
            revision = digest.hexdigest()
            body = dict(
                operation="upload",
                user_id=user_id,
                session_id=sid,
                path=path,
                expected_revision=expected,
                revision=revision,
            )
            previous = self.store.receipt(bot_id, command.request_id, body)
            if previous:
                return previous
            lock = self.action_locks.setdefault(sid, asyncio.Lock())
            if lock.locked() or self.store.active(bot_id):
                raise Conflict(
                    "Stop the agent or acquire human control before uploading.",
                    code="human_control",
                )
            async with self.mutex(bot_id), lock:
                previous = self.store.receipt(bot_id, command.request_id, body)
                if previous:
                    return previous
                await self.existing(bot_id, sid)
                if self.store.active(bot_id) or self.control.state(bot_id)["lease"]:
                    raise Conflict(
                        "Release human control and stop the agent before uploading.",
                        code="human_control",
                    )
                blob_id = self.blobs.reserve(
                    bot_id,
                    sid,
                    path,
                    revision,
                    size,
                    mimetypes.guess_type(path)[0] or "application/octet-stream",
                )
                token = (
                    await sandbox.files("upload_begin", path=path, expected_revision=expected)
                )["token"]
                offset = 0
                with temp_path.open("rb") as source:
                    while raw := await self.store.database.offload(lambda: source.read(65536)):
                        await sandbox.files(
                            "upload_chunk",
                            token=token,
                            offset=offset,
                            data=base64.b64encode(raw).decode(),
                        )
                        offset += len(raw)
                await sandbox.files("upload_commit", token=token, revision=revision)
                token = None
                temp_path.replace(self.blobs.directory / blob_id)
                upload_id = identifier("upload")
                result = {
                    "id": upload_id,
                    "artifact_id": blob_id,
                    "path": path,
                    "revision": revision,
                    "size": size,
                }
                with self.store.transaction() as db:
                    db.execute(
                        "INSERT INTO uploads VALUES (?,?,?,?,?,?,?,?,?)",
                        (
                            upload_id,
                            bot_id,
                            user_id,
                            sid,
                            computer["generation"],
                            blob_id,
                            path,
                            revision,
                            stamp(),
                        ),
                    )
                    self.store._event(db, bot_id, "file.uploaded", result)
                    self.store._save_receipt(db, bot_id, command.request_id, body, result)
                return result
        except BaseException:
            if blob_id:
                self.blobs.discard(blob_id)
            raise
        finally:
            temp_path.unlink(missing_ok=True)
            if token:
                await asyncio.shield(sandbox.files("drop", token=token))
            await upload.close()

    async def attachments(self, bot_id, user_id, ids):
        result = []
        for attachment_id in ids:
            with self.store.transaction() as db:
                row = db.execute(
                    "SELECT * FROM uploads WHERE id=? AND bot_id=? AND user_id=?",
                    (attachment_id, bot_id, user_id),
                ).fetchone()
            if not row:
                raise Conflict("Attachment not found or not owned by you.")
            _, sandbox = await self.existing(bot_id, row["session_id"])
            if await sandbox.file_revision(row["path"]) != row["revision"]:
                raise Conflict("Attachment revision changed; upload or select it again.")
            result.append({"id": row["id"], "path": row["path"], "revision": row["revision"]})
        return result


def attachment_response(files, bot_id, blob_id, request=None):
    result = files.blobs.get(bot_id, blob_id)
    if not result:
        raise HTTPException(404, "Artifact unavailable.")
    meta, path = result
    if protected(meta["path"]):
        raise HTTPException(403, "Protected content.")
    response = FileResponse(
        path,
        media_type=meta["mime"],
        filename=meta["path"].rsplit("/", 1)[-1],
        headers={
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "private, no-store",
            "X-Artifact-Id": blob_id,
            "X-Content-Revision": meta["revision"],
        },
    )
    if request is None:
        return response

    async def content():
        with path.open("rb") as source:
            while True:
                try:
                    request_bot(request, bot_id)
                except HTTPException:
                    return
                chunk = source.read(65536)
                if not chunk:
                    return
                yield chunk
                await asyncio.sleep(0)

    return StreamingResponse(
        content(),
        media_type=meta["mime"],
        headers={**dict(response.headers), "Content-Length": str(meta["size"])},
    )


def register_file_routes(app):
    files = app.state.runtime.files
    base = "/api/bots/{bot_id}/sessions/{sid}"

    @app.exception_handler(SandboxError)
    @app.exception_handler(WorkspacePathError)
    async def sandbox_error(_request, exc):
        from fastapi.responses import JSONResponse

        return JSONResponse({"detail": str(exc)}, status_code=409)

    @app.get(base + "/files")
    async def listing(
        bot_id: str,
        sid: str,
        request: Request,
        path: str = "/workspace",
        cursor: str = "",
    ):
        request_bot(request, bot_id)
        _, sandbox = await files.existing(bot_id, sid)
        return await sandbox.files("list", path=path, cursor=cursor)

    @app.get(base + "/file-preview")
    async def preview(bot_id: str, sid: str, request: Request, path: str):
        request_bot(request, bot_id)
        _, sandbox = await files.existing(bot_id, sid)
        return await sandbox.files("preview", path=path)

    @app.get(base + "/file-content")
    async def download(bot_id: str, sid: str, request: Request, path: str, revision: str):
        request_bot(request, bot_id)
        return attachment_response(
            files, bot_id, await files.snapshot(bot_id, sid, path, revision), request
        )

    @app.get("/api/bots/{bot_id}/artifacts/{artifact_id}/content")
    async def artifact(bot_id: str, artifact_id: str, request: Request):
        request_bot(request, bot_id)
        return attachment_response(files, bot_id, artifact_id, request)

    @app.post(base + "/uploads", status_code=201)
    async def upload(bot_id: str, sid: str, request: Request):
        user, _ = request_bot(request, bot_id)
        async with request.form(max_files=1, max_fields=4, max_part_size=65536) as form:
            try:
                command = Command(request_id=str(form.get("request_id", "")))
            except ValidationError:
                raise HTTPException(422, "Invalid upload request ID.")
            value = form.get("file")
            if not hasattr(value, "read") or not form.get("expected_revision"):
                raise HTTPException(422, "Send file, path, expected_revision and request_id.")
            return await files.upload(
                bot_id,
                sid,
                user.id,
                command,
                value,
                str(form.get("path", "")),
                str(form["expected_revision"]),
            )
