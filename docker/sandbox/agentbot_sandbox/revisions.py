#!/usr/bin/env python3
"""Bounded, descriptor-relative workspace revisions and checked text writes."""

import base64
from contextlib import contextmanager
import hashlib
import json
import os
import stat
import sys
import uuid

ROOT = "/workspace"
LIMIT = 64 * 1024 * 1024


def parts(path):
    if path.startswith("/workspace/"):
        path = path[len("/workspace/") :]
    if (
        path.startswith("/")
        or "\\" in path
        or any(p in {"", ".", ".."} for p in path.split("/"))
    ):
        raise ValueError("Invalid confined workspace path")
    return path.split("/")


@contextmanager
def parent(path, create=False):
    names = parts(path)
    fd = os.open(ROOT, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for name in names[:-1]:
            if create:
                try:
                    os.mkdir(name, mode=0o755, dir_fd=fd)
                except FileExistsError:
                    pass
            child = os.open(
                name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd
            )
            os.close(fd)
            fd = child
        yield fd, names[-1]
    finally:
        os.close(fd)


def digest_at(fd, name, budget):
    file = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
    try:
        if not stat.S_ISREG(os.fstat(file).st_mode):
            raise ValueError("Revision requires a regular file")
        digest = hashlib.sha256()
        while data := os.read(file, 65536):
            budget[0] -= len(data)
            if budget[0] < 0:
                raise ValueError("Workspace revision exceeds 64 MiB")
            digest.update(data)
        return digest.hexdigest()
    finally:
        os.close(file)


def file_revision(path):
    try:
        with parent(path) as (fd, name):
            return digest_at(fd, name, [LIMIT])
    except FileNotFoundError:
        return "missing"


def workspace_revision():
    digest, budget, count = hashlib.sha256(), [LIMIT], [0]

    def visit(fd, prefix):
        for name in sorted(os.listdir(fd)):
            count[0] += 1
            if count[0] > 2000:
                raise ValueError("Workspace revision exceeds 2000 entries")
            info = os.stat(name, dir_fd=fd, follow_symlinks=False)
            path = prefix + name
            digest.update(path.encode() + b"\0" + str(info.st_mode).encode() + b"\0")
            if stat.S_ISDIR(info.st_mode):
                child = os.open(
                    name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd
                )
                try:
                    visit(child, path + "/")
                finally:
                    os.close(child)
            else:
                digest.update(digest_at(fd, name, budget).encode())

    fd = os.open(ROOT, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        visit(fd, "")
    finally:
        os.close(fd)
    return digest.hexdigest()


def write(path, content, expected=None):
    if len(content) > 65536:
        raise ValueError("Text writes are limited to 64 KiB")
    with parent(path, create=True) as (fd, name):
        try:
            current = digest_at(fd, name, [LIMIT])
        except FileNotFoundError:
            current = "missing"
        if expected is not None and current != expected:
            raise ValueError("File revision changed; request fresh approval")
        temporary = ".agentbot-write-" + uuid.uuid4().hex
        mode = (
            0o644
            if current == "missing"
            else stat.S_IMODE(os.stat(name, dir_fd=fd, follow_symlinks=False).st_mode)
        )
        file = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            mode,
            dir_fd=fd,
        )
        try:
            with os.fdopen(file, "wb") as stream:
                stream.write(content)
            os.replace(temporary, name, src_dir_fd=fd, dst_dir_fd=fd)
        finally:
            try:
                os.unlink(temporary, dir_fd=fd)
            except FileNotFoundError:
                pass


if __name__ == "__main__":
    try:
        operation = sys.argv[1]
        if operation == "workspace":
            result = workspace_revision()
        elif operation == "file":
            result = file_revision(sys.argv[2])
        elif operation == "write":
            write(
                sys.argv[2],
                base64.b64decode(sys.argv[3], validate=True),
                sys.argv[4] if len(sys.argv) > 4 else None,
            )
            result = "written"
        else:
            raise ValueError("Unknown revision operation")
        print(json.dumps({"ok": True, "result": result}))
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc)}))
        sys.exit(1)
