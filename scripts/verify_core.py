"""Build and import the actual core wheel without repository paths or extras."""

import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

root = Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory(prefix="agentbot-core-") as temporary:
    directory = Path(temporary)
    source = directory / "source"
    source.mkdir()
    shutil.copyfile(root / "packages/agentbot/pyproject.toml", source / "pyproject.toml")
    shutil.copytree(root / "packages/agentbot/src/agentbot", source / "src/agentbot",
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    wheels = directory / "wheels"
    subprocess.run(["uv", "build", "--wheel", "--out-dir", str(wheels), str(source)], check=True, capture_output=True)
    wheel, = wheels.glob("*.whl")
    with zipfile.ZipFile(wheel) as archive:
        assert not {"agentbot/adapters/ufo.py", "agentbot/tools/blob.py", "agentbot/workflows/blob_orders.py", "agentbot/tools/messaging.py"}.intersection(archive.namelist())
    environment = directory / "venv"
    subprocess.run(["uv", "venv", "--python", sys.executable, str(environment)], check=True, capture_output=True)
    python = environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    subprocess.run(["uv", "pip", "install", "--python", str(python), str(wheel)], check=True, capture_output=True)
    subprocess.run([str(python), "-I", "-c", "import agentbot.kernel, agentbot.events, agentbot.interfaces, agentbot.registry; from importlib.util import find_spec; assert all(find_spec(name) is None for name in ('fastapi', 'docker', 'anthropic', 'agent_framework', 'agentbot_tools')); print('Installed core wheel passed isolated imports without extras')"], cwd=directory, check=True)
