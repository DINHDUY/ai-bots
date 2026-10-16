"""Local consent and process fencing, independent of backend availability."""

import threading
import time
from typing import Literal


class LocalState:
    def __init__(self):
        self.lock = threading.RLock()
        self.sharing = False
        self.armed = False
        self.revision = 0
        self.reason = "Sharing is off"
        self.scope: Literal["window", "display"] = "window"
        self.window = ""
        self.last_contact = 0.0

    def change(self, *, sharing=None, armed=None, scope=None, window=None, reason=""):
        with self.lock:
            if sharing is not None:
                self.sharing = sharing
            if scope is not None:
                if scope not in {"window", "display"}:
                    raise ValueError("Invalid sharing scope")
                self.scope = scope
            if window is not None:
                self.window = window
            if armed is not None:
                self.armed = armed
            if not self.sharing:
                self.armed = False
            self.revision += 1
            self.reason = reason

    def stop(self, reason="Stopped locally"):
        self.change(armed=False, reason=reason)

    def check(self, *, write=False):
        with self.lock:
            if time.monotonic() - self.last_contact > 15:
                self.stop("Backend connection lost")
            if not self.sharing or (write and not self.armed):
                raise RuntimeError(self.reason or "Enable sharing/control locally")
            return self.revision
