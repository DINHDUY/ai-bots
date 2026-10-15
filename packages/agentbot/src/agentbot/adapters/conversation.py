"""Bound historical context without promoting old messages to instructions."""

import re


def bounded_history(messages, *, max_messages=12, max_chars=12000):
    """Keep a recent suffix; never silently truncate a credential or task mid-message."""
    recent = []
    remaining = max_chars
    for message in reversed(messages):
        role, content = message.get("role"), message.get("content")
        if role not in {"user", "assistant"} or not isinstance(content, str):
            continue
        if len(recent) >= max_messages or len(content) > remaining:
            break
        recent.append({"role": role, "content": content})
        remaining -= len(content)
    return list(reversed(recent))


def conversational_intent(prompt):
    """Only recognize whole, unambiguous phrases; mixed task requests still run."""
    text = re.sub(r"[.!?]+$", "", prompt.strip().casefold()).strip()
    if text in {"hi", "hello", "hey", "good morning", "good afternoon", "good evening"}:
        return "greeting"
    if text in {
        "status",
        "status update",
        "what is the status",
        "what's the status",
        "are you there",
    }:
        return "status"
    return "task"
