"""Offline database-and-blob snapshots, with fenced verification restores."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sqlite3
import stat
from datetime import UTC, datetime
from pathlib import Path

from agentbot_control.process_lock import ProcessLock


def _linked(path: Path) -> bool:
    return path.is_symlink() or bool(getattr(path.lstat(), "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT)


def _files(directory: Path) -> list[Path]:
    files: list[Path] = []
    if _linked(directory):
        raise ValueError("Snapshot directories cannot be links")
    for path in directory.rglob("*"):
        if _linked(path) or not path.resolve().is_relative_to(directory.resolve()):
            raise ValueError("Snapshot cannot follow links outside its directory")
        if path.is_file():
            files.append(path)
    return files


def _hash(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def create(database: Path, destination: Path) -> dict:
    database, destination = database.resolve(), destination.resolve()
    if not database.is_file():
        raise ValueError("Database must exist")
    blobs = database.with_suffix(".blobs")
    if destination.is_relative_to(blobs):
        raise ValueError("Backup destination cannot be inside source blobs")
    lock = ProcessLock(database.with_suffix(".runtime.lock"))
    lock.acquire()
    try:
        source_files = _files(blobs) if blobs.exists() else []
        destination.mkdir(parents=True, exist_ok=False)
        # SQLite's backup API includes committed WAL pages. No service starts here.
        source = sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)
        target = sqlite3.connect(destination / "control.sqlite")
        try:
            source.backup(target)
        finally:
            target.close()
            source.close()
        for path in source_files:
            output = destination / "control.blobs" / path.relative_to(blobs)
            output.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, output)
        manifest = {
            "version": 1, "created_at": datetime.now(UTC).isoformat(),
            "files": {p.relative_to(destination).as_posix(): _hash(p) for p in _files(destination)},
            "keys_included": False,
        }
        # Written last: absence means an interrupted, unusable backup.
        (destination / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        return {"files": len(manifest["files"]), "created_at": manifest["created_at"]}
    finally:
        lock.release()


def restore(snapshot: Path, destination: Path) -> Path:
    snapshot, destination = snapshot.resolve(), destination.resolve()
    manifest = json.loads((snapshot / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("version") != 1 or "control.sqlite" not in manifest.get("files", {}):
        raise ValueError("Incomplete or unsupported backup")
    actual = {p.relative_to(snapshot).as_posix() for p in _files(snapshot)} - {"manifest.json"}
    if actual != set(manifest["files"]):
        raise ValueError("Backup contents do not match its manifest")
    for relative, digest in manifest["files"].items():
        path = snapshot / relative
        if not path.resolve().is_relative_to(snapshot) or _hash(path) != digest:
            raise ValueError("Backup integrity verification failed")
    destination.mkdir(parents=True, exist_ok=False)
    database = destination / "control.sqlite"
    # This marker survives an interrupted copy and prevents accidental provider adoption.
    database.with_suffix(".restore-only").write_text(
        "Verification restore: fence the original deployment and review provider identities before activation.\n",
        encoding="utf-8",
    )
    for relative in manifest["files"]:
        output = destination / relative
        output.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(snapshot / relative, output)
    return database


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    create_parser = commands.add_parser("create")
    create_parser.add_argument("--database", type=Path, required=True)
    create_parser.add_argument("--destination", type=Path, required=True)
    restore_parser = commands.add_parser("restore-for-verification")
    restore_parser.add_argument("--snapshot", type=Path, required=True)
    restore_parser.add_argument("--destination", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "create":
        print(json.dumps(create(args.database, args.destination)))
    else:
        restore(args.snapshot, args.destination)
        print("Backup verified and restored; application startup remains fenced.")


if __name__ == "__main__":
    main()
