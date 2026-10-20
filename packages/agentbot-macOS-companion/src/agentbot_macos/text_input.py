"""Literal Unicode input, with a focus/session fence before each small batch."""

EVENT_TAG = 0x4147424F54


def require_released_modifiers() -> None:
    import Quartz as Q

    from agentbot_macos.results import NotDispatched

    modifiers = (
        Q.kCGEventFlagMaskCommand
        | Q.kCGEventFlagMaskControl
        | Q.kCGEventFlagMaskAlternate
        | Q.kCGEventFlagMaskShift
    )
    if Q.CGEventSourceFlagsState(Q.kCGEventSourceStateCombinedSessionState) & modifiers:
        raise NotDispatched(
            "Release physical modifier keys before agent input", "physical_modifier"
        )


def type_text(text: str, check) -> None:
    import Quartz as Q

    source = Q.CGEventSourceCreate(Q.kCGEventSourceStatePrivate)
    for offset in range(0, len(text), 16):
        check()
        require_released_modifiers()
        part = text[offset : offset + 16]
        for down in (True, False):
            event = Q.CGEventCreateKeyboardEvent(source, 0, down)
            Q.CGEventSetFlags(event, 0)
            Q.CGEventSetIntegerValueField(event, Q.kCGEventSourceUserData, EVENT_TAG)
            Q.CGEventKeyboardSetUnicodeString(event, len(part.encode("utf-16-le")) // 2, part)
            Q.CGEventPost(Q.kCGHIDEventTap, event)
