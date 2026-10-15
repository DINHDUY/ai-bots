"""Session lifecycle that stays blind to any one agent framework."""

from __future__ import annotations

import json
import logging
import re
import time
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from typing import Any

from agentbot.events import RealTimeEventStreamer
from agentbot.interfaces import ISandboxClient, SandboxFactory
from agentbot.models import ModelConfig
from agentbot.registry import FrameworkRegistry

logger = logging.getLogger("AgentBotKernel")

_SESSION_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


class SessionStore:
    """JSON file memory for one gateway process."""

    def __init__(self, directory: Path) -> None:
        self._directory = directory

    def load(self, session_id: str) -> list[dict[str, Any]]:
        path = self._path(session_id)
        if not path.exists():
            return []
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            logger.warning("Ignoring unreadable session memory for %s", session_id)
            return []
        if not isinstance(data, list):
            return []
        messages: list[dict[str, Any]] = []
        for item in data:
            if isinstance(item, dict) and item.get("role") in {"user", "assistant"}:
                messages.append({"role": item["role"], "content": str(item.get("content", ""))})
        return messages

    def save(self, session_id: str, messages: list[dict[str, Any]]) -> None:
        path = self._path(session_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(messages, indent=2), encoding="utf-8")
        temporary.replace(path)

    def delete(self, session_id: str) -> None:
        path = self._path(session_id)
        path.unlink(missing_ok=True)

    def _path(self, session_id: str) -> Path:
        validate_session_id(session_id)
        return self._directory / f"{session_id}.json"


def validate_session_id(session_id: str) -> str:
    if not _SESSION_ID.fullmatch(session_id or ""):
        raise ValueError("session_id must be 1-64 characters of letters, digits, '_' or '-'.")
    return session_id


class EngineRuntimeManager:
    """Framework-blind kernel. It only consumes the requested adapter name."""

    def __init__(
        self,
        registry: FrameworkRegistry,
        sandboxes: SandboxFactory,
        sessions: SessionStore,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.registry = registry
        self.sandboxes = sandboxes
        self.sessions = sessions
        self._clock = clock
        self._activity: dict[str, float] = {}
        self._busy: dict[str, int] = {}

    def touch(self, session_id: str) -> None:
        self._activity[session_id] = self._clock()

    async def process_agent_request(
        self,
        target_framework: str,
        user_prompt: str,
        session_id: str,
        streamer: RealTimeEventStreamer,
        instructions: str = "",
        model: ModelConfig | None = None,
        *,
        conversation_id: str | None = None,
        memory_context: list[dict[str, Any]] | None = None,
        sandbox: ISandboxClient | None = None,
        persist_history: bool = True,
    ) -> AsyncIterator[dict[str, Any]]:
        validate_session_id(session_id)
        prompt = user_prompt.strip()
        if not prompt:
            raise ValueError("Prompt is required.")
        logger.info("--- Launching Request Lifecycle Context for Session %s ---", session_id)
        self._busy[session_id] = self._busy.get(session_id, 0) + 1
        self.touch(session_id)
        result_text = ""
        try:
            sandbox = sandbox or await self.sandboxes.get_or_create(session_id)
            conversation_id = conversation_id or session_id
            context = (
                list(memory_context)
                if memory_context is not None
                else self.sessions.load(conversation_id)
            )
            adapter = self.registry.resolve(target_framework)
            await adapter.initialize(
                sandbox=sandbox,
                memory_context=context,
                state_streamer=streamer,
                instructions=instructions,
                model=model,
            )
            async for frame in adapter.execute_step(prompt):
                self.touch(session_id)
                if frame.get("event") == "log" and frame.get("type") == "RESULT":
                    result_text = str(frame.get("payload", ""))
                yield frame
            context.append({"role": "user", "content": prompt})
            context.append({"role": "assistant", "content": result_text})
            if persist_history:
                self.sessions.save(conversation_id, context)
        finally:
            remaining = self._busy.get(session_id, 1) - 1
            if remaining > 0:
                self._busy[session_id] = remaining
            else:
                self._busy.pop(session_id, None)
            self.touch(session_id)

    async def close_session(self, session_id: str) -> None:
        validate_session_id(session_id)
        self._activity.pop(session_id, None)
        await self.sandboxes.close(session_id)

    async def close_idle(self, max_idle_seconds: float) -> list[str]:
        now = self._clock()
        stale = [
            session_id
            for session_id, seen in self._activity.items()
            if session_id not in self._busy and now - seen >= max_idle_seconds
        ]
        for session_id in stale:
            await self.close_session(session_id)
        return stale
