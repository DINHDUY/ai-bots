"""Load only hash-verified OI modules in the isolated native worker."""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
from queue import SimpleQueue


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Open-Interface module unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class OpenInterface:
    def __init__(self, source: Path, manifest: Path):
        self.source = source
        for entry in json.loads(manifest.read_text())["files"]:
            if entry["kind"] != "oi":
                continue
            path = source / entry["path"]
            if (
                path.is_symlink()
                or hashlib.sha256(path.read_bytes()).hexdigest() != entry["patched_sha256"]
            ):
                raise RuntimeError("Open-Interface source/patch verification failed")
        self.interpreter = load_module(
            source / "app/interpreter.py", "agentbot_oi_interpreter"
        ).Interpreter(SimpleQueue())
        self.screen = load_module(source / "app/utils/screen.py", "agentbot_oi_screen").Screen()
        self.llm_class = load_module(source / "app/llm.py", "agentbot_oi_llm").LLM

    def execute(self, function: str, parameters: dict) -> None:
        self.interpreter.execute_function(function, parameters)

    def screenshot(self):
        return self.screen.get_screenshot()

    def context(self) -> str:
        return self.llm_class(None).read_context_txt_file()
