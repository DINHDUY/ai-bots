"""Literal Unicode typing for observed editors, without shortcut parsing."""

import ctypes


def validate_text(text):
    if not isinstance(text, str) or not 1 <= len(text) <= 2000:
        raise ValueError("Typed text must contain 1 to 2000 characters")
    if any(ord(char) < 32 or 0x7F <= ord(char) <= 0x9F or char in "\u2028\u2029" for char in text):
        raise ValueError("Typed text must be one line without control characters")
    try:
        return text.encode("utf-16-le")
    except UnicodeEncodeError as exc:
        raise ValueError("Typed text must contain valid Unicode") from exc


class KeyboardInput(ctypes.Structure):
    _fields_ = [
        ("vk", ctypes.c_uint16), ("scan", ctypes.c_uint16),
        ("flags", ctypes.c_uint32), ("time", ctypes.c_uint32),
        ("extra", ctypes.c_size_t),
    ]


class MouseInput(ctypes.Structure):
    _fields_ = [
        ("x", ctypes.c_int32), ("y", ctypes.c_int32),
        ("data", ctypes.c_uint32), ("flags", ctypes.c_uint32),
        ("time", ctypes.c_uint32), ("extra", ctypes.c_size_t),
    ]


class InputData(ctypes.Union):
    _fields_ = [("keyboard", KeyboardInput), ("mouse", MouseInput)]


class Input(ctypes.Structure):
    _fields_ = [("type", ctypes.c_uint32), ("data", InputData)]


def type_literal(text, check, *, user32=None):
    validate_text(text)
    if user32 is None:
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        user32.SendInput.argtypes = [ctypes.c_uint32, ctypes.POINTER(Input), ctypes.c_int]
        user32.SendInput.restype = ctypes.c_uint32
        user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
        user32.GetAsyncKeyState.restype = ctypes.c_int16
    # Each packet contains a Unicode code unit, never a virtual shortcut key.
    for start in range(0, len(text), 32):
        check()
        if any(user32.GetAsyncKeyState(key) & 0x8000 for key in (0x10, 0x11, 0x12, 0x5B, 0x5C)):
            raise RuntimeError("Release modifier keys before typing text")
        chunk = text[start:start + 32].encode("utf-16-le")
        units = [int.from_bytes(chunk[i:i + 2], "little") for i in range(0, len(chunk), 2)]
        packets = (Input * (len(units) * 2))()
        for index, unit in enumerate(units):
            packets[index * 2] = Input(1, InputData(keyboard=KeyboardInput(0, unit, 0x4, 0, 0)))
            packets[index * 2 + 1] = Input(1, InputData(keyboard=KeyboardInput(0, unit, 0x6, 0, 0)))
        if user32.SendInput(len(packets), packets, ctypes.sizeof(Input)) != len(packets):
            raise RuntimeError("Windows did not accept all text input; inspect the draft before retrying")
    return "Literal text input dispatched; observe the editor to verify the draft"


def register_type_text(check):
    """Add one bounded command to UFO's existing UI control executor."""
    from ufo.automator.ui_control.controller import ControlCommand, ControlReceiver

    @ControlReceiver.register
    class TypeTextCommand(ControlCommand):
        @classmethod
        def name(cls):
            return "type_text"

        def execute(self):
            return type_literal(self.params["text"], check)
