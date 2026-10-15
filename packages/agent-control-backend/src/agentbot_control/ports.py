"""Consumer contracts for run commands; collaborators never receive Runtime."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable, Sequence
from typing import Protocol

from agentbot_control.store import Bot, User


class StartRun(Protocol):
    async def __call__(
        self, user: User, bot: Bot, request_id: str, prompt: str,
        trigger: str = "user", attachment_ids: Sequence[str] = (),
        program: Callable[..., AsyncIterator[dict]] | None = None, resume_sid: str | None = None,
        allowed_policy_id: str = "*", run_mode: str = "computer",
        channel_delivery_id: str | None = None,
    ) -> dict: ...


class StopRun(Protocol):
    def __call__(self, bot_id: str, rid: str, request_id: str, *, cancel_channel: bool = True) -> dict: ...
