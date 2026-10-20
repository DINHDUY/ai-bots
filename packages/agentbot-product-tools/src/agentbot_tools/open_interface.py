"""Open-Interface product adapter using the server-owned action dispatcher."""

from __future__ import annotations

import asyncio
import json
from typing import cast

from agentbot.execution import RunYield as PeerWait
from agentbot.interfaces import ActionResult, IAgentFrameworkAdapter
from agentbot.tools import ToolAccess
from agentbot.tools.registry import legacy_selection
from agentbot_macos import OI_REVISION
from agentbot_macos.controller import NativeRuntimeClient, OiController

from agentbot_tools.oi_messaging import WorkspaceConversation
from agentbot_tools.registry import REGISTRY


class OiAgentAdapter(IAgentFrameworkAdapter):
    def __init__(self, *, completion=None, max_steps=30):
        self.completion, self.max_steps = completion, max_steps

    async def initialize(
        self, sandbox, memory_context, state_streamer, instructions="", model=None
    ):
        if model is None or model.provider not in {"openai", "azure_foundry"}:
            raise ValueError(
                "Open-Interface requires an owner-configured multimodal OpenAI-compatible model"
            )
        self.sandbox, self.streamer, self.model = sandbox, state_streamer, model
        self.runtime = cast(NativeRuntimeClient, sandbox)
        self.instructions, self.context = instructions, memory_context
        self.tool_access = state_streamer.context.tool_access or ToolAccess(
            legacy_selection("open_interface", REGISTRY), registry=REGISTRY
        )

    async def execute_step(self, prompt):
        conversation = WorkspaceConversation(self.streamer, self.completion or self._complete)
        if getattr(self.sandbox, "communication_only", False):
            async for frame in conversation.run(prompt, self.instructions, self.max_steps):
                yield frame
            return
        self.tool_access.require("macos_desktop")
        controller = OiController(self.runtime, conversation.completion)
        await controller.start(prompt, self.instructions, self.context[-10:])
        yield self.streamer.emit_log(
            "OpenInterface",
            "SYSTEM",
            f"Open-Interface {OI_REVISION}; one approved macOS action at a time",
        )
        corrections = 0
        for _ in range(self.max_steps):
            self.tool_access.require("macos_desktop")
            try:
                proposed = await controller.next()
            except PeerWait:
                return
            if proposed.get("peer_handled"):
                yield self.streamer.emit_log("OpenInterface", "TOOL_CALL", proposed["peer_handled"])
                continue
            if proposed.get("proposal_rejected"):
                corrections += 1
                if corrections > 2:
                    raise RuntimeError("Open-Interface returned three invalid action proposals")
                continue
            if proposed.get("finished"):
                if not proposed.get("effect_observed"):
                    raise RuntimeError(
                        "Open-Interface finished without a verified postcondition: "
                        + proposed.get("text", "")
                    )
                yield self.streamer.emit_log(
                    "OpenInterface",
                    "RESULT",
                    proposed.get("text", "Task completed with observed evidence"),
                )
                return
            action = proposed["action"]

            async def execute():
                value = await self.runtime.execute_macos(action)
                return ActionResult(bool(value.get("ok")), value.get("text", ""), value=value)

            result = None
            async for frame in self.streamer.execute_action(
                "OpenInterface",
                "macos." + action["function"],
                action,
                proposed.get("application", "Mac")
                + " · "
                + action["function"]
                + "\n"
                + json.dumps(action["arguments"], ensure_ascii=False),
                execute,
            ):
                if isinstance(frame, ActionResult):
                    result = frame
                else:
                    yield frame
            if result is None:
                raise RuntimeError("macOS action result missing")
            value = result.value if isinstance(result.value, dict) else {}
            await controller.result(
                {"ok": result.ok, "text": result.text, "cancelled": result.cancelled, **value}
            )
            if not result.ok:
                if (
                    not value.get("dispatched", True)
                    and not value.get("outcome_unknown")
                    and value.get("code")
                    in {"stale_target", "permit_expired", "editor_not_focused"}
                    and not result.cancelled
                    and corrections < 2
                ):
                    corrections += 1
                    continue
                raise RuntimeError("macOS action denied or failed: " + result.text)
        raise RuntimeError("Open-Interface observation limit reached")

    async def _complete(self, messages):
        from openai import AsyncOpenAI

        if len(json.dumps(messages)) > 8 * 1024 * 1024:
            raise ValueError("Inference context exceeds limit")
        endpoint = (
            self.model.endpoint.rstrip("/") + "/openai/v1/"
            if self.model.provider == "azure_foundry"
            else None
        )
        async with AsyncOpenAI(
            api_key=self.model.api_key, base_url=endpoint, timeout=60, max_retries=0
        ) as client:
            response = await asyncio.wait_for(
                client.chat.completions.create(
                    model=self.model.model, messages=messages, max_completion_tokens=4096
                ),
                65,
            )
        text = response.choices[0].message.content or ""
        if len(text) > 32000:
            raise ValueError("Model response exceeds limit")
        return text
