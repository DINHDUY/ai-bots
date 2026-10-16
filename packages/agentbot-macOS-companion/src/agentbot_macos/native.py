"""Native observation and one-action execution in an isolated user-session worker."""

from __future__ import annotations

import time
import uuid

from agentbot_macos import accessibility as ax
from agentbot_macos.actions import MacAction
from agentbot_macos.capture import screenshot, windows
from agentbot_macos.detection import detect
from agentbot_macos.protocol import MAX_OBSERVATION_AGE, digest
from agentbot_macos.results import NotDispatched, unknown
from agentbot_macos.session import require_session
from agentbot_macos.text_input import type_text


class NativeRuntime:
    def __init__(self, oi):
        self.oi = oi
        self.observation = None
        self.handles = {}

    def observe(self, scope: str, selected: str, revision: int) -> dict:
        session = require_session()
        available = windows()
        window = next((w for w in available if w["id"] == selected), None)
        if scope == "window" and window is None:
            raise NotDispatched(
                "Select an available primary-display window locally", "window_required"
            )
        if scope == "display" and window is None:
            window = next((w for w in available if w["foreground"]), None)
        if scope == "display":
            deadline = time.monotonic() + 3
            for visible in available:
                if time.monotonic() > deadline:
                    raise NotDispatched(
                        "Display inspection exceeded its limit; share one window",
                        "unsupported_surface",
                    )
                ax.inspect(visible)
        controls, self.handles = ax.inspect(window) if window else ([], {})
        capture = screenshot(scope, window, self.oi)
        self.observation = {
            "observation_id": uuid.uuid4().hex,
            "created_at": time.time(),
            "console_session": session["console_session"],
            "revision": revision,
            "scope": scope,
            "selected": selected,
            "window_id": window["id"] if window else "",
            "window": window,
            "windows": available if scope == "display" else [window],
            "controls": controls,
            "capture": capture,
            "ocr_allowed": bool(window),
        }
        return self.observation

    def detect(self, query: str = "") -> dict:
        if not self.observation:
            raise ValueError("Observe before detecting UI elements")
        return {
            "observation_id": self.observation["observation_id"],
            "elements": detect(self.observation, query),
        }

    def execute(
        self, action: MacAction, scope: str, selected: str, revision: int, expires_at: float
    ) -> dict:
        observation = self.observation
        dispatched = False

        def check():
            if time.time() > expires_at:
                raise NotDispatched("Execution permit expired", "permit_expired")
            if (
                observation is None
                or action.observation_id != observation["observation_id"]
                or time.time() - observation["created_at"] > MAX_OBSERVATION_AGE
            ):
                raise NotDispatched("Observation expired", "stale_target")
            require_session(observation["console_session"])
            if (scope, selected, revision) != (
                observation["scope"],
                observation["selected"],
                observation["revision"],
            ):
                raise NotDispatched("Local sharing changed", "stale_target")
            if action.function in {"launch_app", "wait"}:
                return
            old = observation["window"]
            current = next((w for w in windows() if w["id"] == action.window_id), None)
            if (
                not old
                or action.window_id != old["id"]
                or not current
                or digest(
                    {k: current[k] for k in ("id", "pid", "created", "bundle_id", "bounds", "name")}
                )
                != digest(
                    {k: old[k] for k in ("id", "pid", "created", "bundle_id", "bounds", "name")}
                )
            ):
                raise NotDispatched("Window identity or geometry changed", "stale_target")
            if action.function != "focus_window" and (
                not current["foreground"] or windows()[0]["id"] != current["id"]
            ):
                raise NotDispatched("Target is not the frontmost unobscured window", "stale_target")
            if action.control_id:
                handle = self.handles.get(action.control_id)
                control = next(
                    (c for c in observation["controls"] if c["id"] == action.control_id), None
                )
                if (
                    not handle
                    or not control
                    or not ax.attribute(handle, "AXEnabled", True)
                    or ax.bounds(handle) != control["bounds"]
                ):
                    raise NotDispatched("UI element changed", "stale_target")
                if action.function in {"type_text", "set_text"}:
                    if not control["editable"] or not ax.attribute(handle, "AXFocused", False):
                        raise NotDispatched("Editor is not focused", "editor_not_focused")
                    if action.function == "set_text" and not control["writable"]:
                        raise NotDispatched(
                            "Editor does not support AX text", "text_method_changed"
                        )

        try:
            check()
            if action.function == "launch_app" and scope != "display":
                raise NotDispatched("Launching requires whole-primary-display sharing")
            from agentbot_macos.text_input import require_released_modifiers

            require_released_modifiers()
            dispatched = action.function != "wait"
            observed = self._perform(action, observation, check)
            return {
                "ok": True,
                "dispatched": action.function != "wait",
                "effect_observed": observed,
                "outcome_unknown": False,
                "code": "",
                "text": "Effect verified"
                if observed
                else "Input dispatched; inspect the next observation",
            }
        except NotDispatched as exc:
            return unknown(str(exc)) if dispatched else exc.result()
        except Exception as exc:
            return (
                unknown(type(exc).__name__ + ": native operation failed")
                if dispatched
                else NotDispatched(str(exc)).result()
            )

    def _perform(self, action, observation, check) -> bool:
        args = action.arguments
        function = action.function
        if function == "wait":
            deadline = time.monotonic() + args["seconds"]
            while time.monotonic() < deadline:
                check()
                time.sleep(min(0.05, max(0, deadline - time.monotonic())))
            return True
        if function == "set_text":
            return ax.set_text(self.handles[action.control_id], args["text"])
        if function == "type_text":
            type_text(args["text"], check)
            return False
        if function == "focus_window":
            import AppKit
            import ApplicationServices as AX

            window = observation["window"]
            app = AppKit.NSRunningApplication.runningApplicationWithProcessIdentifier_(
                window["pid"]
            )
            if not app or not app.activateWithOptions_(
                AppKit.NSApplicationActivateIgnoringOtherApps
            ):
                raise RuntimeError("Application activation failed")
            if AX.AXUIElementPerformAction(ax.window_element(window), "AXRaise"):
                raise RuntimeError("Window activation failed")
            return False
        if function == "launch_app":
            import AppKit

            workspace = AppKit.NSWorkspace.sharedWorkspace()
            url = workspace.URLForApplicationWithBundleIdentifier_(args["bundle_id"])
            if not url:
                raise RuntimeError("Allowlisted application is not installed")
            from agentbot_macos.capture import callback_result

            configuration = AppKit.NSWorkspaceOpenConfiguration.configuration()
            callback_result(
                lambda cb: workspace.openApplicationAtURL_configuration_completionHandler_(
                    url, configuration, cb
                )
            )
            return False
        if function == "key_input":
            keys = args["keys"]
            self.oi.execute(
                "hotkey" if len(keys) > 1 else "press", {"keys": keys if len(keys) > 1 else keys[0]}
            )
            return False
        if function == "scroll":
            x, y, w, h = observation["window"]["bounds"]
            self.oi.execute("scroll", {"clicks": args["amount"], "x": x + w / 2, "y": y + h / 2})
            return False
        x, y, w, h = observation["window"]["bounds"]
        if action.control_id and "x" not in args:
            c = next(c for c in observation["controls"] if c["id"] == action.control_id)
            cx, cy, cw, ch = c["bounds"]
            px, py = cx + cw / 2, cy + ch / 2
        else:
            px, py = x + args["x"] * max(0, w - 1), y + args["y"] * max(0, h - 1)
        if not x <= px < x + w or not y <= py < y + h:
            raise RuntimeError("Coordinate escaped the selected window")
        if function == "click":
            self.oi.execute(
                "click",
                {
                    "x": px,
                    "y": py,
                    "button": args.get("button", "left"),
                    "clicks": 2 if args.get("double") else 1,
                    "interval": 0.1,
                },
            )
        elif function == "move":
            self.oi.execute("moveTo", {"x": px, "y": py})
        else:
            self.oi.execute("moveTo", {"x": px, "y": py})
            check()
            self.oi.execute(
                "dragTo",
                {
                    "x": x + args["to_x"] * (w - 1),
                    "y": y + args["to_y"] * (h - 1),
                    "duration": args["duration"],
                    "button": "left",
                },
            )
        return False
