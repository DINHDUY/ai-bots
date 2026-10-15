from agentbot.sandbox.desktop_plan import COMPUTER_ACTIONS, plan_action


def test_every_computer_action_has_a_plan() -> None:
    samples = {
        "screenshot": {},
        "zoom": {"region": [0, 0, 20, 20]},
        "left_click": {"coordinate": [10, 12], "text": "shift"},
        "right_click": {"coordinate": [1, 1]},
        "middle_click": {},
        "double_click": {"coordinate": [2, 3]},
        "triple_click": {"coordinate": [2, 3]},
        "left_click_drag": {"start_coordinate": [1, 1], "coordinate": [8, 8]},
        "mouse_move": {"coordinate": [4, 5]},
        "left_mouse_down": {},
        "left_mouse_up": {},
        "cursor_position": {},
        "scroll": {"scroll_direction": "down", "scroll_amount": 3, "coordinate": [9, 9]},
        "type": {"text": "hello"},
        "key": {"text": "ctrl+s", "repeat": 2},
        "hold_key": {"text": "shift", "duration": 0.1},
        "wait": {"duration": 0.2},
    }
    assert set(samples) == set(COMPUTER_ACTIONS)
    for name, params in samples.items():
        plan = plan_action(name, params)
        assert plan.error is None, name
        assert plan.kind


def test_click_holds_modifier_around_the_click() -> None:
    plan = plan_action("left_click", {"coordinate": [10, 12], "text": "ctrl+shift"})
    commands = [step.argv for step in plan.steps]
    assert commands[0] == ("xdotool", "keydown", "ctrl")
    assert commands[1] == ("xdotool", "keydown", "shift")
    assert commands[2] == ("xdotool", "mousemove", "--sync", "10", "12", "click", "1")
    assert commands[-1] == ("xdotool", "keyup", "ctrl")


def test_key_repeat_is_clamped() -> None:
    plan = plan_action("key", {"text": "Tab", "repeat": 500})
    assert plan.error is not None


def test_coordinate_outside_the_screen_is_rejected() -> None:
    plan = plan_action("mouse_move", {"coordinate": [5000, 1]})
    assert plan.error is not None


def test_unknown_action_is_an_error_plan() -> None:
    plan = plan_action("dance", {})
    assert plan.kind == "error"
