"""Build an offline, hash-pinned Linux host wheel bundle on the target architecture."""

import hashlib
import platform
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path


def main():
    if sys.platform != "linux" or sys.version_info < (3, 11):
        raise SystemExit(
            "Build on Linux with Python >=3.11 matching the host architecture. Use Ubuntu 24.04/WSL or your Linux build runner."
        )
    root = Path(__file__).resolve().parents[2]
    output = root / "artifacts" / "azure"
    output.mkdir(parents=True, exist_ok=True)
    archive = (
        output
        / f"agentbot-host-{platform.machine()}-py{sys.version_info.major}{sys.version_info.minor}.zip"
    )
    with tempfile.TemporaryDirectory(prefix="agentbot-wheels-") as temporary:
        subprocess.run(
            [
                sys.executable,
                "-m",
                "pip",
                "wheel",
                "--wheel-dir",
                temporary,
                str(root / "packages/agentbot"),
                str(root / "packages/agentbot-computer-agent"),
            ],
            check=True,
        )
        with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
            for wheel in sorted(Path(temporary).glob("*.whl")):
                bundle.write(wheel, wheel.name)
    for path in (archive, root / "deploy/azure/bootstrap.sh"):
        with path.open("rb") as stream:
            checksum = hashlib.file_digest(stream, "sha256").hexdigest()
        print(f"{checksum}  {path}")
    print(
        "Publish these immutable artifacts to approved HTTPS locations, then set their URLs and hashes in the operator profile."
    )


if __name__ == "__main__":
    main()
