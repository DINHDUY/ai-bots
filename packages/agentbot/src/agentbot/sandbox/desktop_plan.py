"""Pure command plans for the 17 computer-use member tools.

The container runner executes these steps with xdotool and scrot.
Nothing in this module touches a display, so unit tests can cover every member.
"""

from __future__ import annotations

from dataclasses import dataclass

SCREEN_WIDTH = 1024
SCREEN_HEIGHT = 768
SCREENSHOT_PATH = "/tmp/agentbot-screen.png"
MAX_HOLD_SECONDS = 30.0
MAX_KEY_REPEAT = 100
MAX_SCROLL_CLICKS = 50
MAX_TYPE_CHARS = 10_000

_CLICK_BUTTON = {
    "left_click": "1",
    "right_click": "3",
    "middle_click": "2",
    "double_click": "1",
    "triple_click": "1",
}
_CLICK_REPEAT = {"double_click": 2, "triple_click": 3}
_SCROLL_BUTTON = {"up": "4", "down": "5", "left": "6", "right": "7"}
_MODIFIERS = {"shift", "ctrl", "alt", "super", "meta"}
COMPUTER_ACTIONS = frozenset(
    {
        "screenshot",
        "zoom",
        "left_click",
        "right_click",
        "middle_click",
        "double_click",
        "triple_click",
        "left_click_drag",
        "mouse_move",
        "left_mouse_down",
        "left_mouse_up",
        "cursor_position",
        "scroll",
        "type",
        "key",
        "hold_key",
        "wait",
    }
)


@dataclass(frozen=True)
class PlanStep:
    argv: tuple[str, ...] | None = None
    sleep: float = 0.0


@dataclass(frozen=True)
class ActionPlan:
    kind: str
    steps: tuple[PlanStep, ...] = ()
    crop: tuple[int, int, int, int] | None = None
    error: str | None = None


def plan_action(name: str, params: dict | None) -> ActionPlan:
    """Translate one computer-use member call into ordered shell steps."""

    payload = params or {}
    if name not in COMPUTER_ACTIONS:
        return ActionPlan(kind="error", error=f"Unknown computer action '{name}'.")
    try:
        if name == "screenshot":
            return ActionPlan(kind="image", steps=(_scrot(),))
        if name == "zoom":
            return ActionPlan(kind="zoom", steps=(_scrot(),), crop=_region(payload.get("region")))
        if name == "cursor_position":
            return ActionPlan(
                kind="position",
                steps=(PlanStep(argv=("xdotool", "getmouselocation", "--shell")),),
            )
        if name == "wait":
            return ActionPlan(kind="wait", steps=(PlanStep(sleep=_duration(payload.get("duration"))),))
        if name == "hold_key":
            combo = _key_combo(payload.get("text"))
            return ActionPlan(
                kind="ok",
                steps=(
                    PlanStep(argv=("xdotool", "keydown", combo)),
                    PlanStep(sleep=_duration(payload.get("duration"))),
                    PlanStep(argv=("xdotool", "keyup", combo)),
                ),
            )
        if name in _CLICK_BUTTON:
            return _click_plan(name, payload)
        if name == "left_click_drag":
            return _drag_plan(payload)
        if name == "mouse_move":
            x_pos, y_pos = _coordinate(payload.get("coordinate"), required=True)
            return ActionPlan(
                kind="ok",
                steps=(PlanStep(argv=("xdotool", "mousemove", "--sync", str(x_pos), str(y_pos))),),
            )
        if name in {"left_mouse_down", "left_mouse_up"}:
            verb = "mousedown" if name == "left_mouse_down" else "mouseup"
            return ActionPlan(kind="ok", steps=(PlanStep(argv=("xdotool", verb, "1")),))
        if name == "scroll":
            return _scroll_plan(payload)
        if name == "type":
            text = str(payload.get("text", ""))
            if not text:
                raise ValueError("type requires text.")
            if len(text) > MAX_TYPE_CHARS:
                raise ValueError(f"type text exceeds {MAX_TYPE_CHARS} characters.")
            return ActionPlan(
                kind="ok",
                steps=(PlanStep(argv=("xdotool", "type", "--delay", "12", "--", text)),),
            )
        if name == "key":
            combo = _key_combo(payload.get("text"))
            repeat = _repeat(payload.get("repeat", 1))
            return ActionPlan(
                kind="ok",
                steps=(PlanStep(argv=("xdotool", "key", "--repeat", str(repeat), combo)),),
            )
    except (TypeError, ValueError) as exc:
        return ActionPlan(kind="error", error=str(exc))
    return ActionPlan(kind="error", error=f"Unhandled computer action '{name}'.")


def _scrot() -> PlanStep:
    return PlanStep(argv=("scrot", "-o", SCREENSHOT_PATH))


def _click_plan(name: str, payload: dict) -> ActionPlan:
    steps: list[PlanStep] = []
    modifiers = _modifiers(payload.get("text"))
    steps.extend(PlanStep(argv=("xdotool", "keydown", key)) for key in modifiers)
    coordinate = payload.get("coordinate")
    button = _CLICK_BUTTON[name]
    repeat = _CLICK_REPEAT.get(name, 1)
    argv: list[str] = ["xdotool"]
    if coordinate is not None:
        x_pos, y_pos = _coordinate(coordinate, required=True)
        argv.extend(["mousemove", "--sync", str(x_pos), str(y_pos)])
    argv.append("click")
    if repeat > 1:
        argv.extend(["--repeat", str(repeat)])
    argv.append(button)
    steps.append(PlanStep(argv=tuple(argv)))
    steps.extend(PlanStep(argv=("xdotool", "keyup", key)) for key in reversed(modifiers))
    return ActionPlan(kind="ok", steps=tuple(steps))


def _drag_plan(payload: dict) -> ActionPlan:
    start_x, start_y = _coordinate(payload.get("start_coordinate"), required=True)
    end_x, end_y = _coordinate(payload.get("coordinate"), required=True)
    modifiers = _modifiers(payload.get("text"))
    steps: list[PlanStep] = [PlanStep(argv=("xdotool", "keydown", key)) for key in modifiers]
    steps.extend(
        [
            PlanStep(argv=("xdotool", "mousemove", "--sync", str(start_x), str(start_y))),
            PlanStep(argv=("xdotool", "mousedown", "1")),
            PlanStep(argv=("xdotool", "mousemove", "--sync", str(end_x), str(end_y))),
            PlanStep(argv=("xdotool", "mouseup", "1")),
        ]
    )
    steps.extend(PlanStep(argv=("xdotool", "keyup", key)) for key in reversed(modifiers))
    return ActionPlan(kind="ok", steps=tuple(steps))


def _scroll_plan(payload: dict) -> ActionPlan:
    direction = str(payload.get("scroll_direction", "")).lower()
    if direction not in _SCROLL_BUTTON:
        raise ValueError("scroll_direction must be up, down, left, or right.")
    amount = int(payload.get("scroll_amount", 1))
    if amount < 1 or amount > MAX_SCROLL_CLICKS:
        raise ValueError(f"scroll_amount must be between 1 and {MAX_SCROLL_CLICKS}.")
    modifiers = _modifiers(payload.get("text"))
    steps: list[PlanStep] = [PlanStep(argv=("xdotool", "keydown", key)) for key in modifiers]
    coordinate = payload.get("coordinate")
    if coordinate is not None:
        x_pos, y_pos = _coordinate(coordinate, required=True)
        steps.append(PlanStep(argv=("xdotool", "mousemove", "--sync", str(x_pos), str(y_pos))))
    steps.append(PlanStep(argv=("xdotool", "click", "--repeat", str(amount), _SCROLL_BUTTON[direction])))
    steps.extend(PlanStep(argv=("xdotool", "keyup", key)) for key in reversed(modifiers))
    return ActionPlan(kind="ok", steps=tuple(steps))


def _coordinate(value: object, *, required: bool) -> tuple[int, int]:
    if value is None:
        if required:
            raise ValueError("A coordinate [x, y] is required.")
        raise ValueError("Missing coordinate.")
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        raise ValueError("Coordinates must be [x, y].")
    x_pos = int(value[0])
    y_pos = int(value[1])
    if x_pos < 0 or y_pos < 0 or x_pos >= SCREEN_WIDTH or y_pos >= SCREEN_HEIGHT:
        raise ValueError(f"Coordinate {[x_pos, y_pos]} is outside {SCREEN_WIDTH}x{SCREEN_HEIGHT}.")
    return x_pos, y_pos


def _region(value: object) -> tuple[int, int, int, int]:
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        raise ValueError("zoom region must be [x0, y0, x1, y1].")
    x0, y0 = _coordinate([value[0], value[1]], required=True)
    x1, y1 = _coordinate([value[2], value[3]], required=True)
    if x1 <= x0 or y1 <= y0:
        raise ValueError("zoom region must have a positive area.")
    return x0, y0, x1, y1


def _modifiers(value: object) -> list[str]:
    if value is None or value == "":
        return []
    if not isinstance(value, str):
        raise ValueError("Modifier text must be a string.")
    keys = [part.strip().lower() for part in value.split("+") if part.strip()]
    if not keys or any(key not in _MODIFIERS for key in keys):
        raise ValueError("Modifiers must be shift, ctrl, alt, super, or meta.")
    return keys


def _key_combo(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("A key combination is required.")
    parts = [part.strip() for part in value.split("+") if part.strip()]
    if not parts:
        raise ValueError("A key combination is required.")
    for part in parts[:-1]:
        if part.lower() not in _MODIFIERS:
            raise ValueError(f"Unsupported modifier '{part}'.")
    if any(char in parts[-1] for char in "\n\r\x00"):
        raise ValueError("Key names cannot contain control characters.")
    return "+".join(part.lower() if part.lower() in _MODIFIERS else part for part in parts)


def _duration(value: object) -> float:
    try:
        seconds = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError) as exc:
        raise ValueError("duration must be a number of seconds.") from exc
    if seconds < 0 or seconds > MAX_HOLD_SECONDS:
        raise ValueError(f"duration must be between 0 and {MAX_HOLD_SECONDS} seconds.")
    return seconds


def _repeat(value: object) -> int:
    try:
        count = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError) as exc:
        raise ValueError("repeat must be an integer.") from exc
    if count < 1 or count > MAX_KEY_REPEAT:
        raise ValueError(f"repeat must be between 1 and {MAX_KEY_REPEAT}.")
    return count
