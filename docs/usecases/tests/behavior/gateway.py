from __future__ import annotations

import json
import threading
import time
from typing import Any

import httpx
import uvicorn
from agentbot.gateway.app import create_app
from websockets.exceptions import ConnectionClosed
from websockets.sync.client import connect

from docs.usecases.tests.behavior.constants import GATEWAY
from docs.usecases.tests.behavior.scripted import Plan


class GatewayServer(uvicorn.Server):
    def install_signal_handlers(self) -> None:
        return


class Engineer:
    """WebSocket client for one engineer session."""

    def __init__(self, url: str, timeout: float = 60) -> None:
        self.timeout = timeout
        self.frames: list[dict[str, Any]] = []
        self.cursor = 0
        self.started = False
        self._cm = connect(url, open_timeout=15, ping_interval=None, close_timeout=5)
        self.ws = self._cm.__enter__()

    def send_start(self, session_id: str, framework: str, prompt: str) -> None:
        self.ws.send(
            json.dumps(
                {
                    "action": "start",
                    "session_id": session_id,
                    "framework": framework,
                    "prompt": prompt,
                }
            )
        )
        self.started = True

    def decide(self, frame: dict[str, Any], decision: str) -> None:
        self.ws.send(
            json.dumps(
                {
                    "action": "approve",
                    "approval_id": frame["approval_id"],
                    "decision": decision,
                }
            )
        )

    def recv(self) -> dict[str, Any]:
        try:
            raw = self.ws.recv(timeout=self.timeout)
        except TimeoutError as exc:
            raise AssertionError(
                f"no gateway frame after {self.timeout}s; saw {frame_names(self.frames)}"
            ) from exc
        except ConnectionClosed as exc:
            raise AssertionError(f"gateway socket closed; saw {frame_names(self.frames)}") from exc
        frame = json.loads(raw)
        self.frames.append(frame)
        return frame

    def next_frame(self) -> dict[str, Any]:
        if self.cursor < len(self.frames):
            frame = self.frames[self.cursor]
            self.cursor += 1
            return frame
        frame = self.recv()
        self.cursor = len(self.frames)
        return frame

    def until(self, predicate) -> dict[str, Any]:
        while True:
            frame = self.next_frame()
            if predicate(frame):
                return frame

    def finish_by_approving(self, session_id: str) -> None:
        while True:
            frame = self.until(
                lambda item: item.get("event") in {"approval_required", "done", "error"}
            )
            if frame["event"] == "error":
                raise AssertionError("gateway error during the pipeline")
            if frame["event"] == "done":
                if frame.get("session_id") != session_id:
                    raise AssertionError(f"done for {frame.get('session_id')}")
                return
            self.decide(frame, "approve")

    def approve_until_bash_result(self) -> None:
        command = "python3 /workspace/etl_orders.py"
        while True:
            frame = self.until(
                lambda item: (
                    item.get("event") in {"approval_required", "done", "error"}
                    or (
                        item.get("event") == "log"
                        and item.get("type") == "TOOL_CALL"
                        and command in str(item.get("payload", ""))
                    )
                )
            )
            if frame["event"] == "error":
                raise AssertionError(str(frame.get("payload", "gateway error")))
            if frame["event"] == "done":
                raise AssertionError("pipeline finished before the bash result")
            if frame["event"] == "approval_required":
                self.decide(frame, "approve")
                continue
            return

    def close(self) -> None:
        try:
            self.ws.send(json.dumps({"action": "close"}))
            deadline = time.time() + 20
            while time.time() < deadline:
                frame = json.loads(self.ws.recv(timeout=2))
                if frame.get("event") == "closed":
                    break
        except Exception:
            pass
        try:
            self._cm.__exit__(None, None, None)
        except Exception:
            pass


def frame_names(frames: list[dict[str, Any]]) -> list[str]:
    return [
        ":".join(
            part
            for part in (
                str(frame.get("event", "")),
                str(frame.get("type", "")),
                str(frame.get("action", "")),
            )
            if part
        )
        for frame in frames
    ]


def assert_no_sas(plan: Plan, frames: list[dict[str, Any]]) -> None:
    if not plan.raw_sas or not plan.curated_sas or plan.raw_sas == plan.curated_sas:
        raise AssertionError("SAS tokens were not issued")
    for frame in frames:
        if frame.get("event") != "log":
            continue
        text = json.dumps(frame)
        if plan.raw_sas in text or plan.curated_sas in text:
            raise AssertionError("a log frame contains a SAS token")


def _start_gateway(context) -> None:
    app = create_app(context.kernel)
    config = uvicorn.Config(app, host="127.0.0.1", port=8000, log_level="warning")
    server = GatewayServer(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.time() + 20
    while time.time() < deadline:
        if server.started:
            break
        time.sleep(0.05)
    else:
        raise AssertionError("gateway did not start on 127.0.0.1:8000")
    deadline = time.time() + 10
    while time.time() < deadline:
        try:
            response = httpx.get(f"{GATEWAY}/health", timeout=1)
        except httpx.HTTPError:
            time.sleep(0.1)
            continue
        if response.status_code == 200:
            context.server = server
            context.server_thread = thread
            return
        time.sleep(0.1)
    raise AssertionError("gateway health check did not succeed")
