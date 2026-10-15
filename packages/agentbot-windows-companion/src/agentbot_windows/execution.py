"""Distinguish rejected input from an operation whose effects are uncertain."""


class ActionNotDispatched(RuntimeError):
    def __init__(self, reason, code="preflight_failed"):
        super().__init__(reason)
        self.code = code

    def result(self):
        return {
            "ok": False,
            "dispatched": False,
            "outcome_unknown": False,
            "effect_observed": False,
            "code": self.code,
            "text": "Action not executed: " + str(self)[:450],
        }


class InputBoundary:
    """Mark the first call that can change the desktop, even if it later raises."""

    def __init__(self):
        self.started = False

    def call(self, function, *args, **kwargs):
        self.started = True
        return function(*args, **kwargs)


def uncertain_result(exc):
    # Preserve the reason without storing worker tracebacks or a second log.
    return {
        "ok": False,
        "outcome_unknown": True,
        "effect_observed": False,
        "text": f"Windows action outcome unknown: {type(exc).__name__}: {exc}"[:500],
    }
