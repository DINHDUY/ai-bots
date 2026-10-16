"""Install pinned native sources and hashed dependencies without pairing or TCC prompts."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "packages/agentbot-macOS-companion"


def install_sources() -> None:
    manifest = json.loads((PACKAGE / "upstream.json").read_text())
    for kind, directory in (("oi", "oi"), ("ufo", "taskstar")):
        destination = ROOT / "data" / directory / "source"
        destination.mkdir(parents=True, exist_ok=True)
        entries = [f for f in manifest["files"] if f["kind"] == kind]
        if all(
            (destination / e["path"]).is_file()
            and hashlib.sha256((destination / e["path"]).read_bytes()).hexdigest()
            == e["patched_sha256"]
            for e in entries
        ):
            continue
        for item in entries:
            url = f"https://raw.githubusercontent.com/{item['repo']}/{item['revision']}/{item['path']}"
            with urllib.request.urlopen(url, timeout=30) as response:
                raw = response.read(2 * 1024 * 1024)
            if hashlib.sha256(raw).hexdigest() != item["sha256"]:
                raise ValueError("Upstream checksum mismatch: " + item["path"])
            path = destination / item["path"]
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(raw)
        subprocess.run(
            [
                "patch",
                "--batch",
                "-p1",
                "-i",
                str(PACKAGE / "patches" / f"{kind}-agent-control.patch"),
            ],
            cwd=destination,
            check=True,
        )
        for item in entries:
            if (
                hashlib.sha256((destination / item["path"]).read_bytes()).hexdigest()
                != item["patched_sha256"]
            ):
                raise ValueError("Patched source checksum mismatch: " + item["path"])


def main() -> None:
    if sys.platform != "darwin":
        raise SystemExit(
            "Native setup requires macOS; portable contracts use the workspace install."
        )
    install_sources()
    python = ROOT / "data/oi/venv/bin/python"
    uv = os.environ.get("AGENTBOT_UV", "uv")
    if not python.exists():
        subprocess.run([uv, "venv", "--python", "3.12", str(python.parents[1])], check=True)
    subprocess.run(
        [
            uv,
            "pip",
            "sync",
            "--python",
            str(python),
            "--require-hashes",
            str(PACKAGE / "requirements-oi.lock"),
        ],
        check=True,
    )
    subprocess.run(
        [uv, "pip", "install", "--python", str(python), "--no-deps", "-e", str(PACKAGE)], check=True
    )
    print("Native environment installed. Run data/oi/venv/bin/agentbot-macos doctor.")


if __name__ == "__main__":
    main()
