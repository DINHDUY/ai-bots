import ctypes

import pytest
from agentbot_windows.protocol import WindowsAction
from agentbot_windows.text_input import Input, type_literal


class User32:
    def __init__(self, *, short_write=False, modifier=False):
        self.batches = []
        self.short_write = short_write
        self.modifier = modifier

    def GetAsyncKeyState(self, key):
        return -32768 if self.modifier else 0

    def SendInput(self, count, packets, size):
        assert size == ctypes.sizeof(Input)
        batch = []
        for index in range(count):
            packet = packets[index]
            keyboard = packet.data.keyboard
            assert packet.type == 1 and keyboard.vk == 0
            assert keyboard.flags == (0x4 if index % 2 == 0 else 0x6)
            assert keyboard.time == keyboard.extra == 0
            batch.append(keyboard.scan)
        assert batch[::2] == batch[1::2]
        self.batches.append(batch[::2])
        return count - 1 if self.short_write else count


def test_unicode_packets_preserve_literal_shortcuts_and_surrogate_pairs():
    user32 = User32()
    text = "a" * 31 + "😀" + " {ENTER} ^s +%() ✓"
    checked = []
    type_literal(text, lambda: checked.append(True), user32=user32)
    assert len(checked) == len(user32.batches) == 2
    decoded = [b"".join(unit.to_bytes(2, "little") for unit in batch).decode("utf-16-le") for batch in user32.batches]
    assert "".join(decoded) == text
    assert all(unit not in {9, 10, 13} for batch in user32.batches for unit in batch)
    assert ctypes.sizeof(Input) == (40 if ctypes.sizeof(ctypes.c_void_p) == 8 else 28)


@pytest.mark.parametrize("text", ["", None, 1, "a" * 2001, "Hi\n", "Hi\r", "\t", "\0", "\x1b", "\x7f", "\x85", "\u2028", "\u2029", "\ud800"])
def test_typed_text_rejects_controls_and_invalid_input_before_any_dispatch(text):
    user32 = User32()
    with pytest.raises(ValueError):
        type_literal(text, lambda: None, user32=user32)
    assert not user32.batches
    with pytest.raises(ValueError):
        WindowsAction(function="type_text", observation_id="observe-test", window_id="1", control_id="2", arguments={"text": text})


def test_typing_requires_an_explicit_observed_editor():
    with pytest.raises(ValueError, match="observed editor"):
        WindowsAction(function="type_text", observation_id="observe-test", window_id="1", arguments={"text": "Hello"})


def test_focus_change_stops_before_another_batch_and_does_not_replay():
    user32 = User32()
    def check():
        if user32.batches:
            raise RuntimeError("Editor lost focus")
    with pytest.raises(RuntimeError, match="lost focus"):
        type_literal("a" * 100, check, user32=user32)
    assert len(user32.batches) == 1


def test_partial_send_stops_without_retry():
    user32 = User32(short_write=True)
    with pytest.raises(RuntimeError, match="did not accept all"):
        type_literal("a" * 100, lambda: None, user32=user32)
    assert len(user32.batches) == 1


def test_physical_modifier_keys_block_typing():
    user32 = User32(modifier=True)
    with pytest.raises(RuntimeError, match="modifier keys"):
        type_literal("Hello", lambda: None, user32=user32)
    assert not user32.batches
