"""Local CLI. Setup and diagnostics never grant permissions or inject input."""

from __future__ import annotations

import argparse
import asyncio
import getpass
import json
import platform
import sys
import threading
from pathlib import Path


def companion_running(root: Path) -> bool:
    """The control socket survives crashes; only the held session lock proves a live companion."""
    import fcntl

    path = root / "session.lock"
    if not path.exists():
        return False
    with path.open("a") as probe:
        try:
            fcntl.flock(probe, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return True
    return False


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["pair", "run", "status", "doctor", "stop", "forget"])
    parser.add_argument("--backend", default="http://127.0.0.1:8000")
    parser.add_argument("--name", default=platform.node()[:100] or "Mac")
    args = parser.parse_args()
    if sys.platform != "darwin":
        raise SystemExit("Native companion commands require macOS")
    from agentbot_macos import credentials
    from agentbot_macos.session import permissions

    if args.command == "doctor":
        result = permissions()
        result["instructions"] = (
            "Enable Screen Recording and Accessibility for the actual companion executable in System Settings → Privacy & Security, then restart the companion."
        )
        print(json.dumps(result, indent=2))
        return
    root = credentials.directory()
    if args.command in {"status", "stop"}:
        from agentbot_macos.local_ipc import request

        print(json.dumps(request(root, args.command), indent=2))
        return
    if args.command == "forget":
        if companion_running(root):
            raise SystemExit(
                "Quit the companion and revoke pairing in Agent Control before forgetting it"
            )
        credentials.forget()
        print("Pairing credential removed; receipts retained.")
        return
    if args.command == "pair":
        if companion_running(root):
            raise SystemExit("Quit the companion before changing its pairing")
        import httpx

        backend = credentials.endpoint(args.backend)
        code = getpass.getpass("One-time pairing code: ")
        with httpx.Client(timeout=15, trust_env=False) as client:
            response = client.post(
                backend + "/api/macos-agents/enroll", json={"code": code, "name": args.name}
            )
            response.raise_for_status()
        credentials.save({**response.json(), "backend": backend, "name": args.name})
        print("Mac paired. Sharing and control remain off until enabled locally.")
        return
    import fcntl

    from agentbot_macos.local_controls import run_menu
    from agentbot_macos.local_ipc import serve
    from agentbot_macos.service import Companion

    lock = (root / "session.lock").open("a")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        raise SystemExit("Another companion is running in this user session")
    repository = Path(__file__).resolve().parents[4]
    companion = Companion(
        credentials.load(),
        repository / "data/oi/source",
        repository / "packages/agentbot-macOS-companion/upstream.json",
        root / "receipts.sqlite",
    )
    loop = asyncio.new_event_loop()

    def background():
        asyncio.set_event_loop(loop)
        loop.run_forever()

    thread = threading.Thread(target=background, daemon=True)
    thread.start()
    asyncio.run_coroutine_threadsafe(companion.run(), loop)
    asyncio.run_coroutine_threadsafe(serve(root, companion), loop)
    try:
        run_menu(companion, loop)
    finally:
        companion.running = False
        asyncio.run_coroutine_threadsafe(companion.local_stop(), loop).result(timeout=5)

        async def shutdown():
            pending = [task for task in asyncio.all_tasks() if task is not asyncio.current_task()]
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)

        asyncio.run_coroutine_threadsafe(shutdown(), loop).result(timeout=10)
        companion.journal.close()
        loop.call_soon_threadsafe(loop.stop)
        thread.join(timeout=5)
        lock.close()


if __name__ == "__main__":
    main()
