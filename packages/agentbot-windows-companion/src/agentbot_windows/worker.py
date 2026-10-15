"""Private stdio worker. No socket listener, credentials, or direct model calls."""

import argparse
import contextlib
import json
import logging
import sys
import time
from pathlib import Path

from .bootstrap import qualify_source
from .execution import ActionNotDispatched
from .protocol import MAX_FRAME, packed


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--kind", choices=["desktop", "planner"], required=True)
    parser.add_argument("--scope", choices=["window", "desktop"], default="window")
    parser.add_argument("--window", type=int, default=0)
    parser.add_argument("--window-pid", type=int, default=0)
    parser.add_argument("--window-created", type=float, default=0.0)
    args = parser.parse_args()
    source = qualify_source(args.source)
    sys.path.insert(0, str(source))
    import os

    os.chdir(source)
    logging.disable(logging.CRITICAL)
    output = sys.stdout
    instance = None
    while raw := sys.stdin.readline(MAX_FRAME + 1):
        try:
            if len(raw.encode()) > MAX_FRAME:
                raise ValueError("Worker message too large")
            command = json.loads(raw)
            with contextlib.redirect_stdout(sys.stderr):
                if args.kind == "desktop":
                    if instance is None:
                        from .native import NativeDesktop

                        instance = NativeDesktop(
                            args.scope,
                            args.window,
                            args.window_pid,
                            args.window_created,
                        )
                    from .win_session import session_check

                    if not session_check()[0]:
                        if command["method"] == "execute":
                            raise ActionNotDispatched("Windows interactive desktop is unavailable")
                        raise RuntimeError("Windows interactive desktop is unavailable")
                    if command["method"] in {"observe", "capture"}:
                        result = instance.read(command["method"])
                    elif command["method"] == "execute":
                        if (
                            not command.get("expires_at")
                            or time.time() > command["expires_at"]
                        ):
                            raise ActionNotDispatched(
                                "Execution permit expired before native dispatch", "permit_expired"
                            )
                        result = instance.execute(
                            command["arguments"], expires_at=command["expires_at"]
                        )
                    else:
                        raise ValueError("Unknown desktop operation")
                else:
                    arguments = command["arguments"]
                    operation = arguments["operation"]
                    if operation == "start":
                        from .planner import UfoPlanner

                        instance = UfoPlanner(
                            arguments["request"],
                            arguments.get("instructions", ""),
                            arguments.get("context", []),
                        )
                        result = {"started": True}
                    elif instance is None:
                        raise ValueError("UFO planning session not started")
                    elif operation == "prompt":
                        result = instance.prompt(arguments["observation"])
                    elif operation == "response":
                        result = instance.response(arguments["response"])
                    elif operation == "result":
                        result = instance.result(arguments["result"])
                    else:
                        raise ValueError("Unknown planner operation")
            answer = {"result": result}
        except ActionNotDispatched as exc:
            answer = {"result": exc.result()}
        except Exception as exc:
            answer = {"error": f"{type(exc).__name__}: {exc}"[:500]}
        encoded = packed(answer)
        if len(encoded.encode()) > MAX_FRAME:
            encoded = packed({"error": "Worker response too large"})
        output.write(encoded + "\n")
        output.flush()


if __name__ == "__main__":
    main()
