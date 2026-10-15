"""Unified event frames for WebSocket clients."""

from __future__ import annotations

import asyncio
import base64
import logging
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from agentbot.tools.context import ToolAccess

from agentbot.interfaces import ActionResult, utc_now

logger = logging.getLogger("AgentBotKernel")


class SkillExecutor(Protocol):
    async def __call__(self, skill_id: str, parameters_json: str = "{}") -> str: ...


class ConnectorPreparation(Protocol):
    def __call__(self, connection_id: str, operation: str, title: str = "", text: str = "") -> dict[str, Any]: ...


@dataclass
class RunContext:
    """Per-turn values the control plane attaches without subclassing the streamer.

    Callback signatures are owned here; product services supply their implementations.
    """

    tool_access: ToolAccess | None = None
    request_intent: str = "user"
    run_mode: str = "computer"
    allowed_policy_id: str = "*"
    authorize: Callable[[], object] | None = None
    sandbox_guard: object | None = None
    connector_tools: list[dict[str, Any]] = field(default_factory=list)
    skill_execute: SkillExecutor | None = None
    connector_prepare: ConnectorPreparation | None = None
    connector_execute: Callable[[dict[str, Any]], Awaitable[ActionResult]] | None = None
    peer_tools: dict[str, Callable[..., Awaitable[str]]] = field(default_factory=dict)
    peer_schemas: list[dict[str, Any]] = field(default_factory=list)
    peer_roster: Callable[[], str] | None = None
    channel_waiting: bool = False
    channel_wait_reason: str = ""


class RealTimeEventStreamer:
    """Builds platform event frames and parks human-approval decisions."""

    def __init__(self, approval_timeout: float = 120.0) -> None:
        self.approval_timeout = approval_timeout
        self._pending: dict[str, asyncio.Future[bool]] = {}
        self.action_handler = None
        self.context = RunContext()

    def pending_ids(self) -> list[str]:
        return list(self._pending)

    def cancel_pending(self, approval_id: str) -> None:
        self._pending.pop(approval_id, None)

    async def execute_action(
        self,
        engine: str,
        operation: str,
        arguments: dict[str, Any],
        detail: str,
        execute: Callable[[], Awaitable[ActionResult]],
        *,
        requires_approval: bool = True,
        step_id: str | None = None,
    ) -> AsyncIterator[dict[str, Any] | ActionResult]:
        """One dispatch contract used by both framework adapters.

        Control installs its durable arbiter; the standalone gateway retains its
        approval wire format and supplies the same structured result contract.
        """
        if self.action_handler:
            async for item in self.action_handler(
                engine,
                operation,
                arguments,
                detail,
                execute,
                requires_approval=requires_approval,
                step_id=step_id,
            ):
                yield item
            return
        if requires_approval:
            frame, future = self.begin_approval(engine, operation, detail)
            yield frame
            if not await self.wait_for_approval(future):
                yield ActionResult(False, "User denied this action.")
                return
        started = utc_now()
        result = await execute()
        result.started_at, result.ended_at = started, utc_now()
        yield result

    def emit_plan(self, engine: str, steps: list[dict[str, str]]) -> dict[str, Any]:
        """Explicit adapter plans only; never infer progress from prose/tool names."""
        if len(steps) > 100 or len({step.get("id") for step in steps}) != len(steps):
            raise ValueError("A plan requires at most 100 unique step IDs.")
        for step in steps:
            if (
                not step.get("id")
                or not step.get("title")
                or len(step["id"]) > 128
                or len(step["title"]) > 512
                or step.get("status")
                not in {"pending", "running", "completed", "failed", "cancelled"}
            ):
                raise ValueError("Invalid plan step.")
        return {"event": "plan_updated", "source": engine, "steps": steps}

    def emit_log(self, engine_name: str, level: str, message: str) -> dict[str, Any]:
        frame = {
            "event": "log",
            "source": engine_name,
            "type": level,
            "payload": message,
        }
        logger.info("event log %s %s", engine_name, level)
        return frame

    def emit_artifact(
        self, engine_name: str, path: str, context: str
    ) -> dict[str, Any]:
        frame = {
            "event": "artifact_written",
            "source": engine_name,
            "meta": {"path": path, "preview": context},
        }
        logger.info("event artifact %s %s", engine_name, path)
        return frame

    def emit_screenshot(self, engine_name: str, image: bytes) -> dict[str, Any]:
        payload = base64.b64encode(image).decode("ascii")
        frame = {
            "event": "log",
            "source": engine_name,
            "type": "SCREENSHOT_CAPTURE",
            "payload": payload,
            "capture": getattr(image, "metadata", None),
        }
        logger.info("event screenshot %s bytes=%s", engine_name, len(image))
        return frame

    def begin_approval(
        self, engine_name: str, action: str, detail: str
    ) -> tuple[dict[str, Any], asyncio.Future[bool]]:
        approval_id = uuid.uuid4().hex
        loop = asyncio.get_running_loop()
        future: asyncio.Future[bool] = loop.create_future()
        self._pending[approval_id] = future
        frame = {
            "event": "approval_required",
            "source": engine_name,
            "approval_id": approval_id,
            "action": action,
            "detail": detail,
        }
        logger.info("event approval %s %s", engine_name, action)
        return frame, future

    def resolve(self, approval_id: str, approved: bool) -> None:
        future = self._pending.pop(approval_id, None)
        if future is not None and not future.done():
            future.set_result(approved)

    async def wait_for_approval(self, future: asyncio.Future[bool]) -> bool:
        try:
            return await asyncio.wait_for(future, self.approval_timeout)
        except TimeoutError:
            if not future.done():
                future.set_result(False)
            return False
