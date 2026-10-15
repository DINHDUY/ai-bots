import ctypes
import struct

import pytest
from agentbot_windows.mouse_activity import MouseActivity
from agentbot_windows.win_session import RawInputHeader, RawMouse, mouse_activity_from_event


def test_empty_reports_do_not_count_as_mouse_activity():
    mouse = MouseActivity()
    assert not mouse.observe(1, 0, 0, 0, 0, 0)
    assert not mouse.observe(1, 4, 0, 0, 0, 0)  # Attribute-change notification.
    assert not mouse.observe(1, 0, 0x400, 0, 0, 0)  # Zero wheel delta.
    assert not mouse.observe(0, 0, 1, 0, 20, 10)  # No physical device.


@pytest.mark.parametrize("x,y", [(1, 0), (-1, 0), (0, 1), (0, -1)])
def test_even_small_relative_movement_still_counts(x, y):
    assert MouseActivity().observe(1, 0, 0, 0, x, y)


@pytest.mark.parametrize("buttons", [1 << bit for bit in range(10)])
def test_button_transitions_still_count_without_movement(buttons):
    assert MouseActivity().observe(1, 0, buttons, 0, 0, 0)


@pytest.mark.parametrize("buttons,delta", [(0x400, 120), (0x400, 0xFF88), (0x800, 120)])
def test_wheel_input_still_counts(buttons, delta):
    assert MouseActivity().observe(1, 0, buttons, delta, 0, 0)


def test_repeated_absolute_reports_are_stationary_but_input_still_counts():
    mouse = MouseActivity()
    assert mouse.observe(1, 1, 0, 0, 32768, 32768)
    assert not mouse.observe(1, 1, 0, 0, 32768, 32768)
    assert mouse.observe(1, 1, 0, 0, 32769, 32768)
    assert mouse.observe(1, 1, 1, 0, 32769, 32768)  # Stationary click.
    assert mouse.observe(2, 1, 0, 0, 32769, 32768)  # Another device.
    assert mouse.observe(1, 3, 0, 0, 32769, 32768)  # Coordinate space changed.
    assert not mouse.observe(1, 3, 0, 0, 32769, 32768)


@pytest.mark.parametrize("x,buttons,delta,expected", [(0, 0, 0, False), (-2, 0, 0, True), (0, 0x400, 120, True)])
def test_native_raw_input_reads_full_windows_mouse_packet(x, buttons, delta, expected):
    # Windows RAWINPUTHEADER + RAWMOUSE wire layout, independent of ctypes fields.
    pointer = "Q" if ctypes.sizeof(ctypes.c_void_p) == 8 else "I"
    header_size = struct.calcsize("<II" + pointer * 2)
    payload = struct.pack("<H2xHHIiiI", 0, buttons, delta, 0, x, 0, 0)
    packet = struct.pack("<II" + pointer * 2, 0, header_size + 24, 42, 0) + payload
    assert ctypes.sizeof(RawInputHeader) == header_size
    assert ctypes.sizeof(RawMouse) == 24

    class User32:
        def GetRawInputData(self, event, command, output, size, cb_header):
            assert event == 123
            assert command == 0x10000003  # RID_INPUT, not RID_HEADER.
            assert cb_header == header_size
            assert size._obj.value == len(packet)
            ctypes.memmove(output, packet, len(packet))
            return len(packet)

    assert mouse_activity_from_event(User32(), 123, MouseActivity()) is expected
