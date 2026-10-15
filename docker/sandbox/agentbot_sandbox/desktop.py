#!/usr/bin/env python3
"""Run one computer-use action inside the sandbox desktop."""

from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from desktop_plan import SCREENSHOT_PATH, plan_action  # noqa: E402

ENV = os.environ.copy()
ENV["DISPLAY"] = ENV.get("DISPLAY", ":99")


def main() -> None:
    name = sys.argv[1]
    params = json.loads(sys.argv[2])
    plan = plan_action(name, params)
    if plan.error:
        _emit({"ok": False, "error": plan.error})
        return
    outputs, error = _run_steps(plan.steps)
    if error:
        _emit({"ok": False, "error": error})
        return
    if plan.kind == "image":
        _emit({"ok": True, "text": "OK", "image_b64": _image_b64(SCREENSHOT_PATH)})
        return
    if plan.kind == "zoom":
        zoom_path = _zoom(plan.crop)
        _emit({"ok": True, "text": "OK", "image_b64": _image_b64(zoom_path)})
        return
    if plan.kind == "position":
        _emit({"ok": True, "text": _position(outputs[-1] if outputs else "")})
        return
    _emit({"ok": True, "text": "OK"})


def _run_steps(steps) -> tuple[list[str] | None, str | None]:
    outputs: list[str] = []
    for step in steps:
        if step.sleep:
            time.sleep(step.sleep)
        if not step.argv:
            continue
        proc = subprocess.run(list(step.argv), capture_output=True, text=True, env=ENV)
        if proc.returncode != 0:
            message = (
                proc.stderr.strip() or proc.stdout.strip() or f"exit {proc.returncode}"
            )
            return None, message
        outputs.append(proc.stdout)
    return outputs, None


def _zoom(crop: tuple[int, int, int, int] | None) -> str:
    if crop is None:
        raise ValueError("zoom region is missing.")
    from PIL import Image

    image = Image.open(SCREENSHOT_PATH).convert("RGB")
    x0, y0, x1, y1 = crop
    cropped = image.crop((x0, y0, x1, y1))
    scale = min(
        image.width / max(cropped.width, 1), image.height / max(cropped.height, 1)
    )
    size = (max(1, int(cropped.width * scale)), max(1, int(cropped.height * scale)))
    resized = cropped.resize(size, Image.Resampling.NEAREST)
    destination = "/tmp/agentbot-zoom.png"
    resized.save(destination, format="PNG")
    return destination


def _position(text: str) -> str:
    x_value = y_value = None
    for line in text.splitlines():
        if line.startswith("X="):
            x_value = line.split("=", 1)[1].strip()
        elif line.startswith("Y="):
            y_value = line.split("=", 1)[1].strip()
    if x_value is None or y_value is None:
        raise ValueError(text.strip() or "cursor position unavailable")
    return f"X={x_value}, Y={y_value}"


def _image_b64(path: str) -> str:
    return base64.b64encode(Path(path).read_bytes()).decode("ascii")


def _emit(payload: dict) -> None:
    if payload.get("image_b64"):
        from datetime import datetime, timezone

        payload["capture"] = {"captured_at": datetime.now(timezone.utc).isoformat()}
        try:
            result = subprocess.run(
                ["xdotool", "getmouselocation", "--shell"],
                capture_output=True,
                text=True,
                timeout=2,
            )
            values = dict(
                line.split("=", 1) for line in result.stdout.splitlines() if "=" in line
            )
            payload["capture"]["cursor"] = {
                "x": int(values["X"]),
                "y": int(values["Y"]),
            }
        except Exception:
            pass
    print(json.dumps(payload), flush=True)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        _emit({"ok": False, "error": str(exc)})
