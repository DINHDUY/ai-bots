"""Reproducible, isolated UFO checkout and auditable compatibility patch."""

import subprocess
from pathlib import Path

from . import UFO_REVISION

PATCHES = {
    "ufo/automator/ui_control/screenshot.py": (
        (
            "screenshot = self.control.capture_as_image()",
            "screenshot = _win32_print_window(self.control.handle)  # Agent Control: window pixels only",
        ),
        (
            "desktop = DesktopPhotographer(all_screens=False)\n            screenshot = desktop.capture()",
            'raise RuntimeError("Window capture unavailable; desktop fallback disabled")',
        ),
    ),
    "ufo/automator/ui_control/controller.py": (
        (
            "expected_text and expected_text not in self.control.window_text()",
            "expected_text != self.control.iface_value.CurrentValue",
        ),
        (
            'except Exception as e:\n            if method_name == "set_text" or method_name == "set_edit_text":',
            'except Exception as e:\n            raise RuntimeError("Literal text input failed; no keystroke fallback") from e\n            if method_name == "set_text" or method_name == "set_edit_text":',
        ),
        (
            'if isinstance(result, str) and result.startswith("An error occurred"):\n            try:\n                if control_focus',
            'if isinstance(result, str) and result.startswith("An error occurred"):\n            raise RuntimeError("Keyboard input failed; no typing fallback")\n            try:\n                if control_focus',
        ),
        (
            'self.atomic_execution("click", params)\n        else:\n            self.atomic_execution("click_input", params)',
            'return self.atomic_execution("click", params)\n        else:\n            return self.atomic_execution("click_input", params)',
        ),
        (
            'self.atomic_execution("wheel_mouse_input", params)\n            return',
            'return self.atomic_execution("wheel_mouse_input", params)\n            return',
        ),
    ),
    "ufo/automator/__init__.py": (
        (
            "from .app_apis import factory",
            "# Agent Control: API/shell/Office receiver registration is disabled",
        ),
    ),
    "ufo/agents/agent/basic.py": (
        (
            'retriever = utils.LazyImport("..rag.retriever")',
            "retriever = None  # Agent Control: no retrieval imports",
        ),
        (
            "self.retriever_factory = retriever.RetrieverFactory()",
            "self.retriever_factory = None  # Agent Control: retrieval is disabled",
        ),
    ),
}


def git(source, *args):
    return subprocess.check_output(
        ["git", "-C", str(source), *args], text=True, encoding="utf-8"
    ).strip()


def qualify_source(source: Path, *, apply=False):
    source = source.resolve()
    if git(source, "rev-parse", "HEAD") != UFO_REVISION:
        raise RuntimeError("UFO checkout must match the supported source revision")
    # Compare expected complete files, not just a marker claiming a patch was applied.
    for path, changes in PATCHES.items():
        original = (
            subprocess.check_output(
                ["git", "-C", str(source), "show", f"{UFO_REVISION}:{path}"]
            )
            .decode("utf-8")
            .replace("\r\n", "\n")
        )
        target = source / path
        current = target.read_text(encoding="utf-8")
        patched, restored = original, current
        for before, after in changes:
            if original.count(before) != 1:
                raise RuntimeError("UFO compatibility patch no longer applies")
            patched = patched.replace(before, after)
            restored = restored.replace(after, before)
        if restored == original and apply:
            target.write_text(patched, encoding="utf-8")
        elif current != patched:
            raise RuntimeError(f"Unqualified UFO source: {path}")
    changed = set(git(source, "diff", "HEAD", "--name-only").splitlines())
    if changed - PATCHES.keys():
        raise RuntimeError("Unexpected modifications in UFO checkout")
    unexpected = git(source, "ls-files", "--others", "--exclude-standard").splitlines()
    if unexpected:
        raise RuntimeError("Unexpected untracked files in UFO checkout")
    return source


def prepare(source: Path):
    if not source.exists():
        subprocess.run(
            [
                "git",
                "clone",
                "--filter=blob:none",
                "--no-checkout",
                "https://github.com/microsoft/UFO.git",
                str(source),
            ],
            check=True,
        )
        subprocess.run(
            [
                "git",
                "-C",
                str(source),
                "sparse-checkout",
                "set",
                "ufo",
                "config",
                "aip",
                "prompts",
            ],
            check=True,
        )
        subprocess.run(["git", "-C", str(source), "checkout", UFO_REVISION], check=True)
    return qualify_source(source, apply=True)
