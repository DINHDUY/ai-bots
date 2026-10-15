"""Explicit pairing and a visible, user-session Windows control panel."""

import argparse
import asyncio
import json
import os
import sys
import threading
import uuid
from pathlib import Path
from urllib.parse import urlparse


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["prepare", "pair", "run", "forget"])
    parser.add_argument("--source", type=Path, default=Path("data/ufo/upstream"))
    parser.add_argument("--backend", default="http://127.0.0.1:8000")
    parser.add_argument(
        "--profile",
        type=Path,
        default=Path(os.getenv("LOCALAPPDATA", ".")) / "AgentControl" / "companion.bin",
    )
    args = parser.parse_args()
    if args.command == "prepare":
        from .bootstrap import prepare

        print(prepare(args.source))
        return
    if os.name != "nt":
        parser.error("Desktop control requires Windows")
    from .win_session import protect, session_check, unprotect, watch_input

    if args.command == "forget":
        args.profile.unlink(missing_ok=True)
        print("Local pairing removed. Revoke the device in Agent Control too.")
        return
    if args.command == "pair":
        import getpass

        import httpx

        parsed = urlparse(args.backend)
        if parsed.scheme != "https" and not (
            parsed.scheme == "http"
            and parsed.hostname in {"localhost", "127.0.0.1", "::1"}
        ):
            parser.error("Remote backends require HTTPS")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            parser.error("Invalid backend URL")
        print(
            f"Pair this Windows account with {args.backend}. The companion starts with sharing and control OFF."
        )
        code = getpass.getpass("Paste the one-time enrollment code from Bot settings: ")
        name = os.environ.get("COMPUTERNAME", "Windows PC")
        with httpx.Client(timeout=15, follow_redirects=False) as client:
            result = client.post(
                args.backend.rstrip("/") + "/api/computer-agents/enroll",
                json={"request_id": uuid.uuid4().hex, "code": code, "name": name},
            )
            result.raise_for_status()
        args.profile.parent.mkdir(parents=True, exist_ok=True)
        args.profile.write_bytes(
            protect(
                json.dumps(
                    {**result.json(), "backend": args.backend.rstrip("/"), "name": name}
                ).encode()
            )
        )
        print("Paired. Run the companion, then enable sharing locally.")
        return
    import tkinter as tk
    from tkinter import ttk

    from .bootstrap import qualify_source
    from .service import Companion

    if sys.version_info[:2] != (3, 11):
        parser.error(
            "Use the isolated Python 3.11 environment created by scripts/windows-companion.ps1 setup"
        )
    source = qualify_source(args.source)
    credentials = json.loads(unprotect(args.profile.read_bytes()))
    from .win_session import desktop_lock

    release_desktop = desktop_lock()
    companion = Companion(
        credentials,
        source,
        args.profile.with_suffix(".receipts.sqlite"),
        session_check=session_check,
    )
    loop = asyncio.new_event_loop()
    thread = threading.Thread(
        target=lambda: (
            asyncio.set_event_loop(loop),
            loop.run_until_complete(companion.run()),
        ),
        daemon=True,
    )
    thread.start()

    def stop(reason="Stopped locally"):
        companion.state.stop(reason)
        asyncio.run_coroutine_threadsafe(companion.stop_workers(reason), loop)

    watcher = watch_input(
        stop, lambda: companion.state.should_pause_on_input(companion.automating)
    )

    def local_ready():
        import psutil
        import win32gui
        import win32process

        ready, session, reason = session_check()
        if ready and not watcher.is_set():
            return False, session, "Local input watcher unavailable"
        if (
            ready
            and companion.state.sharing
            and companion.scope == "window"
            and not win32gui.IsWindow(companion.desktop.window)
        ):
            return False, session, "Select an open window to share"
        if ready and companion.state.sharing and companion.scope == "window":
            try:
                pid = win32process.GetWindowThreadProcessId(companion.desktop.window)[1]
                if (
                    pid,
                    psutil.Process(pid).create_time(),
                ) != companion.desktop.window_identity:
                    return False, session, "Shared application changed; select it again"
            except Exception:
                return False, session, "Shared application unavailable"
        return ready, session, reason

    companion.session_check = local_ready
    root = tk.Tk()
    root.title("Agent Control · This Windows PC")
    root.geometry("600x460")
    panel = ttk.Frame(root, padding=18)
    panel.pack(fill="both", expand=True)
    ttk.Label(panel, text="This Windows PC", font=("Segoe UI", 15, "bold")).pack(
        anchor="w"
    )
    ttk.Label(panel, text=credentials["backend"]).pack(anchor="w", pady=(4, 12))
    sharing, armed, whole = tk.BooleanVar(), tk.BooleanVar(), tk.BooleanVar()
    hand_off = tk.BooleanVar(value=companion.state.hand_off)
    status = tk.StringVar()
    targets = {}
    target = ttk.Combobox(panel, state="readonly", width=65)
    target.pack(anchor="w", pady=6)

    def refresh_windows():
        import win32gui

        targets.clear()

        def collect(hwnd, _):
            title = win32gui.GetWindowText(hwnd)
            if title and win32gui.IsWindowVisible(hwnd) and title != root.title():
                targets[f"{title[:70]} ({hwnd})"] = hwnd

        win32gui.EnumWindows(collect, None)
        target["values"] = list(targets)

    def select_window(_=None):
        import psutil
        import win32process

        stop("Shared window changed")
        companion.desktop.window = targets.get(target.get(), 0)
        try:
            pid = win32process.GetWindowThreadProcessId(companion.desktop.window)[1]
            companion.desktop.window_identity = (pid, psutil.Process(pid).create_time())
        except Exception:
            companion.desktop.window = 0
            companion.desktop.window_identity = (0, 0.0)

    target.bind("<<ComboboxSelected>>", select_window)
    ttk.Button(panel, text="Refresh window list", command=refresh_windows).pack(
        anchor="w"
    )
    refresh_windows()

    def change_scope():
        stop("Sharing scope changed")
        companion.scope = "desktop" if whole.get() else "window"

    def share():
        companion.state.change(
            sharing=sharing.get(), armed=False, reason="Control is off"
        )
        asyncio.run_coroutine_threadsafe(
            companion.stop_workers("Screen sharing changed"), loop
        )

    def arm():
        ready, _, reason = session_check()
        ready = (
            ready
            and companion.state.sharing
            and watcher.is_set()
            and (whole.get() or companion.desktop.window != 0)
        )
        if not armed.get():
            reason = "Local control is off"
        elif not companion.state.sharing:
            reason = "Enable Share screen before allowing agent control"
        elif ready:
            reason = "Local control enabled"
        else:
            reason = reason or "Select a window and check the local input watcher"
        companion.state.change(
            armed=bool(armed.get() and ready),
            reason=reason,
        )

    ttk.Checkbutton(panel, text="Share screen", variable=sharing, command=share).pack(
        anchor="w", pady=4
    )
    ttk.Checkbutton(
        panel,
        text="Share whole primary display instead of the selected window",
        variable=whole,
        command=change_scope,
    ).pack(anchor="w", pady=4)
    ttk.Checkbutton(
        panel, text="Allow agent control", variable=armed, command=arm
    ).pack(anchor="w", pady=4)
    ttk.Checkbutton(
        panel,
        text="Hand off",
        variable=hand_off,
        command=lambda: companion.state.set_hand_off(hand_off.get()),
    ).pack(anchor="w", pady=4)
    ttk.Label(
        panel,
        text="Keep the agent running when you use the mouse or keyboard. "
        "STOP and Ctrl+Alt+F12 still pause it.",
        wraplength=520,
    ).pack(anchor="w", padx=(20, 0))
    ttk.Button(panel, text="STOP · Ctrl+Alt+F12", command=stop).pack(
        anchor="w", pady=10
    )
    ttk.Label(panel, textvariable=status, wraplength=480).pack(anchor="w")
    ttk.Label(
        panel,
        text="This status describes the connection and local permissions. "
        "Check Agent Control for the bot's task status.",
        wraplength=520,
    ).pack(anchor="w", pady=(6, 0))

    def refresh():
        armed.set(companion.state.armed)
        sharing.set(companion.state.sharing)
        status.set(companion.status + " · " + companion.state.reason)
        root.after(300, refresh)

    def close():
        companion.state.change(sharing=False, armed=False, reason="Companion closed")
        stop("Companion closed")
        asyncio.run_coroutine_threadsafe(companion.stop_workers(), loop).result(
            timeout=5
        )
        companion.running = False
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", close)
    refresh()
    try:
        root.mainloop()
    finally:
        release_desktop()


if __name__ == "__main__":
    main()
