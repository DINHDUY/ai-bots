#!/usr/bin/env python3
"""Confined workspace files with bounded chunks and immutable read snapshots."""

import base64
import fnmatch
import hashlib
import heapq
import json
import mimetypes
import os
from pathlib import Path
import re
import stat
import sys
import uuid

from revisions import parent, digest_at, parts

ROOT = Path("/tmp/agentbot-files")
LIMIT = 64 * 1024 * 1024
CHUNK = 65536


def protected(path):
    name = path.replace("\\", "/").rsplit("/", 1)[-1].lower()
    return any(
        fnmatch.fnmatchcase(name, pattern)
        for pattern in (
            ".env",
            ".env.*",
            "*.env",
            "*.pem",
            "*.key",
            "*.p12",
            "*.pfx",
            "credentials",
            "credentials.json",
            "id_rsa",
            "id_ed25519",
        )
    )


def target_path(path, root=False):
    if root and path in {"", ".", "/workspace"}:
        return "/workspace"
    return "/workspace/" + "/".join(parts(path))


def listing(path, cursor):
    target = target_path(path, True)
    if target == "/workspace":
        fd = os.open(target, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    else:
        with parent(target) as (directory, name):
            fd = os.open(
                name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory
            )
    try:
        with os.scandir(fd) as iterator:
            names = heapq.nsmallest(
                201, (entry.name for entry in iterator if entry.name > cursor)
            )
        entries = []
        for name in names[:200]:
            info = os.stat(name, dir_fd=fd, follow_symlinks=False)
            kind = (
                "file"
                if stat.S_ISREG(info.st_mode)
                else "directory"
                if stat.S_ISDIR(info.st_mode)
                else "unsupported"
            )
            path = target + "/" + name
            entries.append(
                {
                    "name": name,
                    "path": path,
                    "kind": kind,
                    "size": info.st_size,
                    "modified_at": info.st_mtime,
                    "protected": protected(path),
                    "revision": None,
                    "operations": ["list"]
                    if kind == "directory"
                    else ["preview", "download"]
                    if kind == "file" and not protected(path)
                    else [],
                }
            )
        return {"entries": entries, "cursor": names[199] if len(names) > 200 else None}
    finally:
        os.close(fd)


def token_paths(token):
    if not re.fullmatch("[a-f0-9]{32}", token):
        raise ValueError("Invalid file token")
    return ROOT / (token + ".bin"), ROOT / (token + ".json")


def snapshot(path, expected=None):
    if protected(path):
        raise PermissionError("Protected file exposes metadata only")
    path = target_path(path)
    token = uuid.uuid4().hex
    data_path, meta_path = token_paths(token)
    digest, size = hashlib.sha256(), 0
    with parent(path) as (directory, name):
        fd = os.open(
            name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory
        )
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_size > LIMIT:
                raise ValueError("File is not regular or exceeds 64 MiB")
            with data_path.open("xb") as output:
                while chunk := os.read(fd, CHUNK):
                    size += len(chunk)
                    if size > LIMIT:
                        raise ValueError("File exceeds 64 MiB")
                    digest.update(chunk)
                    output.write(chunk)
            after = os.fstat(fd)
            revision = digest.hexdigest()
            if (after.st_mtime_ns, after.st_size) != (
                info.st_mtime_ns,
                info.st_size,
            ) or (expected and revision != expected):
                raise ValueError("File revision changed")
        except BaseException:
            data_path.unlink(missing_ok=True)
            raise
        finally:
            os.close(fd)
    meta = {
        "token": token,
        "path": path,
        "size": size,
        "revision": revision,
        "mime": mimetypes.guess_type(path)[0] or "application/octet-stream",
    }
    meta_path.write_text(json.dumps(meta))
    return meta


def commit(token, revision):
    source, metadata = token_paths(token)
    meta = json.loads(metadata.read_text())
    if "expected_revision" not in meta:
        raise ValueError("Not an upload")
    with parent(meta["path"], create=True) as (directory, name):
        try:
            current = digest_at(directory, name, [LIMIT])
        except FileNotFoundError:
            current = "missing"
        if current != meta["expected_revision"]:
            raise ValueError("Destination revision changed")
        temporary = ".upload-" + uuid.uuid4().hex
        fd = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            0o644,
            dir_fd=directory,
        )
        try:
            digest, total = hashlib.sha256(), 0
            with os.fdopen(fd, "wb") as out, source.open("rb") as inp:
                while chunk := inp.read(CHUNK):
                    total += len(chunk)
                    if total > LIMIT:
                        raise ValueError("Upload exceeds 64 MiB")
                    digest.update(chunk)
                    out.write(chunk)
            if digest.hexdigest() != revision:
                raise ValueError("Uploaded bytes changed")
            os.replace(temporary, name, src_dir_fd=directory, dst_dir_fd=directory)
        finally:
            try:
                os.unlink(temporary, dir_fd=directory)
            except FileNotFoundError:
                pass
    source.unlink(missing_ok=True)
    metadata.unlink(missing_ok=True)
    return {"path": meta["path"], "revision": revision, "size": total}


def dispatch(request):
    ROOT.mkdir(mode=0o700, exist_ok=True)
    operation = request["operation"]
    if operation == "changes":
        try:
            return json.loads(Path("/tmp/agentbot-file-changes.json").read_text())
        except FileNotFoundError:
            return {"epoch": "unknown", "sequence": 0, "rescan": True, "overflow": True}
    if operation == "list":
        return listing(request.get("path", "/workspace"), request.get("cursor", ""))
    if operation in {"snapshot", "preview"}:
        if protected(request["path"]) and operation == "preview":
            return {
                "protected": True,
                "path": request["path"],
                "text": "",
                "truncated": False,
                "returned_bytes": 0,
            }
        meta = snapshot(request["path"], request.get("revision"))
        if operation == "snapshot":
            return meta
        data, metadata = token_paths(meta["token"])
        with data.open("rb") as source:
            raw = source.read(CHUNK)
        data.unlink()
        metadata.unlink()
        return {
            **meta,
            "text": raw.decode("utf-8", errors="replace"),
            "encoding": "utf-8",
            "returned_bytes": len(raw),
            "truncated": meta["size"] > len(raw),
            "protected": False,
        }
    if operation == "upload_begin":
        path = target_path(request["path"])
        if protected(path):
            raise PermissionError("Protected files require a dedicated secret flow")
        token = uuid.uuid4().hex
        data, metadata = token_paths(token)
        data.touch(exist_ok=False)
        metadata.write_text(
            json.dumps(
                {"path": path, "expected_revision": request["expected_revision"]}
            )
        )
        return {"token": token}
    data, metadata = token_paths(request["token"])
    if operation == "drop":
        data.unlink(missing_ok=True)
        metadata.unlink(missing_ok=True)
        return {}
    if operation == "read":
        offset = int(request["offset"])
        if offset < 0 or offset > LIMIT:
            raise ValueError("Invalid offset")
        with data.open("rb") as source:
            source.seek(offset)
            raw = source.read(CHUNK)
        return {
            "data": base64.b64encode(raw).decode(),
            "offset": offset,
            "eof": len(raw) < CHUNK,
        }
    if operation == "upload_chunk":
        raw = base64.b64decode(request["data"], validate=True)
        if (
            len(raw) > CHUNK
            or data.stat().st_size != request["offset"]
            or request["offset"] + len(raw) > LIMIT
        ):
            raise ValueError("Invalid upload offset or size")
        with data.open("ab") as destination:
            destination.write(raw)
        return {"offset": request["offset"] + len(raw)}
    if operation == "upload_commit":
        return commit(request["token"], request["revision"])
    raise ValueError("Unknown file operation")


if __name__ == "__main__":
    try:
        print(json.dumps({"ok": True, "result": dispatch(json.loads(sys.argv[1]))}))
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc)}))
        sys.exit(1)
