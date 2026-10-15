"""Distinguish physical mouse activity from empty or stationary HID reports."""


class MouseActivity:
    def __init__(self):
        self.absolute_positions = {}

    def observe(self, device, flags, buttons, button_data, x, y):
        if not device:
            return False
        # Button transitions and nonzero vertical/horizontal wheel deltas.
        button_activity = bool(buttons & 0x03FF or (buttons & 0x0C00 and button_data))
        if flags & 0x01:  # MOUSE_MOVE_ABSOLUTE, including touch/tablet devices.
            position = (bool(flags & 0x02), x, y)  # Virtual vs primary desktop.
            previous = self.absolute_positions.get(device)
            self.absolute_positions[device] = position
            # An unknown first position is conservatively treated as activity.
            return button_activity or previous != position
        self.absolute_positions.pop(device, None)
        return button_activity or bool(x or y)
