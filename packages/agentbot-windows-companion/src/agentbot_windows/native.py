"""Native UFO executor. Construct receivers only after validating an action."""

from __future__ import annotations

import base64
import os
import subprocess
import time
import uuid
from datetime import UTC, datetime
from io import BytesIO

from .execution import ActionNotDispatched, InputBoundary, uncertain_result
from .protocol import MAX_OBSERVATION_AGE, WindowsAction, digest


class NativeDesktop:
    def __init__(
        self, scope="window", window_handle=0, window_pid=0, window_created=0.0
    ):
        import ctypes

        ctypes.windll.user32.SetThreadDpiAwarenessContext(ctypes.c_void_p(-4))
        import psutil
        import win32gui

        # Registers only UI controls, not the API/shell receiver factories.
        from config.config_loader import get_ufo_config
        from ufo.automator.ui_control.inspector import ControlInspectorFacade

        ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
        config = get_ufo_config()
        config.system.input_text_api = "set_text"
        config.system.input_text_enter = False
        config.system.click_api = "click_input"
        config.system.show_visual_outline_on_screen = False
        config.system.maximize_window = False
        self.inspector = ControlInspectorFacade("uia")
        self.win32gui, self.psutil = win32gui, psutil
        self.user32 = ctypes.windll.user32
        self.scope = scope
        self.window = None
        self.window_handle = window_handle
        self.window_pid, self.window_created = window_pid, window_created
        self.observations = {}
        self.sequence = 0

    def info(self, window):
        rect = window.rectangle()
        pid = window.process_id()
        process = self.psutil.Process(pid)
        return {
            "handle": window.handle,
            "pid": pid,
            "created": process.create_time(),
            "process": process.name(),
            "name": window.window_text()[:200],
            "rect": [rect.left, rect.top, rect.right, rect.bottom],
            "dpi": self.user32.GetDpiForWindow(window.handle),
        }

    @staticmethod
    def fresh(control):
        # UFO caches inspection properties. Actions must read current UIA values,
        # including the result of a value-pattern write, rather than cached labels.
        from pywinauto.controls.uiawrapper import UIAWrapper
        from pywinauto.uia_element_info import UIAElementInfo

        return UIAWrapper(UIAElementInfo(control.element_info._element))

    @staticmethod
    def writable_text(control):
        if control.element_info.control_type not in {"Edit", "Document", "ComboBox"}:
            return False
        try:
            return callable(getattr(control, "set_edit_text", None)) and not control.iface_value.CurrentIsReadOnly
        except Exception:
            return False

    @staticmethod
    def text_input_method(control):
        if not NativeDesktop.writable_text(control):
            return None
        # Teams uses CKEditor, whose UIA value-write path can fail despite
        # advertising a writable value. Choose typing before any write attempt.
        if "ck-editor__editable" in (getattr(control.element_info, "class_name", "") or ""):
            return "type_text"
        return "set_edit_text"

    def check_shared_window(self):
        if self.scope == "window" and self.window is not None and self.window_pid:
            info = self.info(self.window)
            if (info["pid"], info["created"]) != (self.window_pid, self.window_created):
                raise RuntimeError(
                    "Shared application was replaced; select it locally again"
                )

    def shared_window(self):
        """Bind only the locally selected HWND, without inspecting other apps."""
        if self.window is None and self.window_handle and self.win32gui.IsWindow(self.window_handle):
            from pywinauto.controls.uiawrapper import UIAWrapper
            from pywinauto.uia_element_info import UIAElementInfo

            self.window = UIAWrapper(UIAElementInfo(handle_or_elem=self.window_handle))
        if self.window is not None and not self.win32gui.IsWindow(self.window.handle):
            self.window = None
        self.check_shared_window()
        return self.window

    def read(self, operation):
        """Retry only reads when an application replaces its UIA elements."""
        if operation not in {"observe", "capture"}:
            raise ValueError("Only observation and capture can be retried")
        from .win_session import session_check

        for attempt in range(3):
            if not session_check()[0]:
                raise RuntimeError("Windows interactive desktop is unavailable")
            try:
                return getattr(self, operation)()
            except Exception as exc:
                # UIA_E_ELEMENTNOTAVAILABLE shares the generic COM message
                # "An event was unable to invoke any of the subscribers".
                hresult = getattr(exc, "hresult", None)
                if not isinstance(hresult, int) or hresult & 0xFFFFFFFF != 0x80040201:
                    raise
                # Discard partial/stale observations and reacquire UIA roots.
                # Keep the locally selected HWND and process identity pinned.
                self.observations.clear()
                self.window = None
                if attempt == 2:
                    raise RuntimeError(
                        f"Windows {operation} could not read the updated application after three attempts "
                        "(UIA element unavailable, 0x80040201). Previous input was not replayed. "
                        "Inspect the application before requesting another action."
                    ) from exc
                time.sleep((0.15, 0.35)[attempt])

    def observe(self):
        if self.scope == "window":
            shared = self.shared_window()
            windows = [shared] if shared is not None else []
        else:
            windows = self.inspector.get_desktop_windows()[:80]
        if self.scope == "desktop":
            width, height = (
                self.user32.GetSystemMetrics(0),
                self.user32.GetSystemMetrics(1),
            )
            windows = [
                w
                for w in windows
                if 0 <= w.rectangle().left < w.rectangle().right <= width
                and 0 <= w.rectangle().top < w.rectangle().bottom <= height
            ]
        foreground = self.win32gui.GetForegroundWindow()
        oid = uuid.uuid4().hex
        record = {
            "time": time.time(),
            "windows": {},
            "controls": {},
            "foreground": foreground,
        }
        public = []
        for window in windows:
            try:
                info = self.info(window)
                wid = str(window.handle)
                info.update(id=wid, kind="window", type=info["process"])
                record["windows"][wid] = (window, info)
                public.append(info)
            except Exception:
                continue
        selected = next(
            (w for w in windows if w.handle == foreground),
            windows[0] if windows else None,
        )
        if self.scope == "desktop":
            self.window = selected
        controls = []
        if selected:
            types = [
                "Button",
                "Edit",
                "CheckBox",
                "ComboBox",
                "List",
                "ListItem",
                "MenuItem",
                "RadioButton",
                "Slider",
                "Spinner",
                "TabItem",
                "TreeItem",
                "Document",
                "DataItem",
                "Hyperlink",
                "Text",
                "Pane",
                "ScrollBar",
            ]
            for i, control in enumerate(
                self.inspector.find_control_elements_in_descendants(
                    selected, control_type_list=types, depth=4
                )[:200]
            ):
                try:
                    control = self.fresh(control)
                    if control.element_info._element.CurrentIsPassword:
                        continue
                    cid = str(i + 1)
                    rect = control.rectangle()
                    info = {
                        "id": cid,
                        "name": control.window_text()[:200],
                        "type": control.element_info.control_type,
                        "kind": "control",
                        "automation_id": control.element_info.automation_id,
                        "writable_text": self.writable_text(control),
                        "text_input_method": self.text_input_method(control),
                        "rect": [rect.left, rect.top, rect.right, rect.bottom],
                    }
                    record["controls"][cid] = (control, digest(info))
                    # Focus is live guidance, not part of the stable target hash.
                    controls.append({
                        **info,
                        "has_keyboard_focus": bool(control.element_info._element.CurrentHasKeyboardFocus),
                    })
                except Exception:
                    continue
        record["selected"] = str(selected.handle) if selected else ""
        self.observations[oid] = record
        self.observations = {
            k: v
            for k, v in self.observations.items()
            if time.time() - v["time"] < MAX_OBSERVATION_AGE
        }
        self.observations = dict(list(self.observations.items())[-8:])
        shot = self.capture() if selected or self.scope == "desktop" else None
        return {
            "observation_id": oid,
            "windows": public,
            "controls": controls,
            "window_id": record["selected"],
            "foreground": foreground,
            "capture": shot,
            "scope": self.scope,
            "captured_at": datetime.now(UTC).isoformat(),
        }

    def capture(self):
        from ufo.automator.ui_control.screenshot import (
            ControlPhotographer,
            DesktopPhotographer,
        )

        if self.scope == "window":
            if self.shared_window() is None:
                raise RuntimeError("Select a shared window before capture")
            image = ControlPhotographer(self.window).capture()
            rect = self.info(self.window)["rect"]
        else:
            image = DesktopPhotographer(all_screens=False).capture()
            rect = [0, 0, image.width, image.height] if image else []
        if image is None:
            raise RuntimeError("Window capture unavailable; no desktop fallback")
        buffer = BytesIO()
        image.convert("RGB").save(buffer, format="PNG")
        self.sequence += 1
        return {
            "image": base64.b64encode(buffer.getvalue()).decode(),
            "width": image.width,
            "height": image.height,
            "sequence": self.sequence,
            "captured_at": datetime.now(UTC).isoformat(),
            "viewport_revision": digest(rect),
            "transform": {
                "bounds": rect,
                "coordinate_space": "physical_pixels",
                "dpi": self.user32.GetDpiForWindow(self.window.handle)
                if self.window
                else 96,
            },
            "title": self.window.window_text()[:200] if self.window else "Desktop",
        }

    def execute(self, payload, *, expires_at):
        boundary = InputBoundary()
        try:
            return self._execute(payload, expires_at=expires_at, boundary=boundary)
        except ActionNotDispatched as exc:
            if boundary.started:
                raise RuntimeError(str(exc)) from exc
            raise
        except Exception as exc:
            if not boundary.started:
                raise ActionNotDispatched(f"{type(exc).__name__}: {exc}") from exc
            raise

    def _execute(self, payload, *, expires_at, boundary):
        from ufo.agents.processors.schemas.actions import ActionCommandInfo
        from ufo.agents.processors.schemas.target import TargetInfo
        from ufo.automator.action_execution import ActionExecutor
        from ufo.automator.puppeteer import AppPuppeteer

        action = WindowsAction.model_validate(payload)

        def gate():
            from .win_session import session_check

            if time.time() > expires_at:
                raise ActionNotDispatched("Execution permit expired", "permit_expired")
            if not session_check()[0]:
                raise ActionNotDispatched("Windows session unavailable")

        gate()
        observed = self.observations.get(action.observation_id)
        if not observed or time.time() - observed["time"] > MAX_OBSERVATION_AGE:
            raise ActionNotDispatched("stale_target: observe again before executing", "stale_target")
        if action.function == "launch_app":
            if self.scope != "desktop":
                raise RuntimeError("Launching an app requires desktop sharing")
            executable = {"notepad": "notepad.exe", "calculator": "calc.exe"}[
                action.arguments["app"]
            ]
            gate()
            boundary.call(subprocess.Popen,
                [os.path.join(os.environ["WINDIR"], "System32", executable)]
            )
            return {
                "ok": True,
                "text": "Application launch dispatched; observe the new window",
                "effect_observed": False,
            }
        item = observed["windows"].get(action.window_id)
        if not item:
            raise ActionNotDispatched("stale_target: window is outside the shared observation", "stale_target")
        window, before = item
        if self.info(window) != {
            k: v for k, v in before.items() if k not in {"id", "kind", "type"}
        }:
            raise ActionNotDispatched("stale_target: window geometry or identity changed", "stale_target")
        if action.function == "select_application_window":
            gate()
            boundary.call(window.set_focus)  # No maximize or outline side effects.
            time.sleep(0.1)
            focused = self.win32gui.GetForegroundWindow() == window.handle
            return {
                "ok": focused,
                "text": "Window focus observed"
                if focused
                else "Windows refused focus; select the application locally",
                "effect_observed": focused,
            }
        if (
            self.win32gui.GetForegroundWindow() != window.handle
            or observed["selected"] != action.window_id
        ):
            raise ActionNotDispatched("stale_target: foreground changed", "stale_target")
        control = None
        if action.control_id:
            entry = observed["controls"].get(action.control_id)
            if not entry:
                raise ActionNotDispatched("stale_target: control not in this observation", "stale_target")
            control = self.fresh(entry[0])
            if control.element_info._element.CurrentIsPassword:
                raise RuntimeError(
                    "stale_target: password controls require local input"
                )
            rect = control.rectangle()
            now = {
                "id": action.control_id,
                "name": control.window_text()[:200],
                "type": control.element_info.control_type,
                "kind": "control",
                "automation_id": control.element_info.automation_id,
                "writable_text": self.writable_text(control),
                "text_input_method": self.text_input_method(control),
                "rect": [rect.left, rect.top, rect.right, rect.bottom],
            }
            if (
                digest(now) != entry[1]
                or not control.is_enabled()
                or not control.is_visible()
            ):
                raise ActionNotDispatched("stale_target: control changed", "stale_target")
        if action.function in {"set_edit_text", "type_text", "click_input"} and control is None:
            raise RuntimeError("This action requires an observed control")
        if action.function == "set_edit_text":
            if self.text_input_method(control) == "type_text":
                raise ActionNotDispatched(
                    "This rich-text editor requires type_text. Observe again and propose literal typing with a new approval.",
                    "text_method_changed",
                )
            if not self.writable_text(control):
                raise ActionNotDispatched(
                    "This control does not support writable UI Automation text input. "
                    "Select an editable text box; no text was sent.",
                    "unsupported_text_control",
                )
        if action.function == "type_text":
            if not self.writable_text(control):
                raise ActionNotDispatched("Select a writable editor for literal typing", "unsupported_text_control")
            if not control.element_info._element.CurrentHasKeyboardFocus:
                raise ActionNotDispatched(
                    "The message editor does not have keyboard focus. Propose click_input on "
                    "the editor with a new approval, observe its focus, then propose type_text. No text was sent.",
                    "editor_not_focused",
                )
            from .text_input import register_type_text

            def check_typing_target():
                gate()
                reason = ""
                if self.win32gui.GetForegroundWindow() != window.handle:
                    reason = "foreground window changed"
                elif not control.element_info._element.CurrentHasKeyboardFocus:
                    reason = "editor lost keyboard focus"
                elif control.element_info._element.CurrentIsPassword:
                    reason = "target became a password control"
                elif not control.is_enabled() or not control.is_visible():
                    reason = "editor is no longer enabled or visible"
                elif self.info(window) != {k: v for k, v in before.items() if k not in {"id", "kind", "type"}}:
                    reason = "window identity, title, or geometry changed"
                if reason:
                    raise RuntimeError(f"Typing stopped: {reason}; inspect the draft before retrying")

            # UFO's receiver normally calls set_focus. The separate editor-click
            # action already established focus; preserve that caret and verify it
            # instead of asking a rich-text provider to focus itself again.
            control.set_focus = check_typing_target
            register_type_text(check_typing_target)
        arguments = dict(action.arguments)
        if action.function == "keyboard_input":
            arguments["control_focus"] = control is not None
        gate()
        puppet = AppPuppeteer(before["process"], before["process"])
        command = ActionCommandInfo(
            function=action.function,
            arguments=arguments,
            target=TargetInfo(
                kind="control",
                id=action.control_id,
                name=control.window_text() if control else "Window",
            ),
        )
        gate()
        result = boundary.call(ActionExecutor().execute,
            command, puppet, {action.control_id: control} if control else {}, window
        )
        if isinstance(result, str) and result.startswith("An error occurred"):
            return uncertain_result(RuntimeError(result[:450]))
        verified = False
        if action.function == "set_edit_text":
            try:
                verified = control.iface_value.CurrentValue == arguments["text"]
            except Exception:
                verified = control.window_text() == arguments["text"]
        return {
            "ok": True,
            "text": "Text value verified"
            if verified
            else "Input dispatched; inspect the following desktop observation for its effect",
            "effect_observed": verified,
        }
