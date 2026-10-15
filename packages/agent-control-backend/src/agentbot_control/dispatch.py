"""Guarded sandbox dispatch and cancellation drain."""

import asyncio

from agentbot.interfaces import (
    CancellableSandbox,
    CheckedSandbox,
    CommandResult,
    TerminationUnverified,
    UncertainSandbox,
)
from agentbot.sandbox.remote import remote_action_id


class GuardedSandbox:
    """Track adapter tool coroutines through cancellation until mutations settle."""

    def __init__(self, sandbox):
        self.sandbox = sandbox
        self.pending = set()
        self.stopping = False
        self.action_context = {}
        self.last_command = None

    def __getattr__(self, name):
        method = getattr(self.sandbox, name)

        async def invoke(*args, **kwargs):
            action_id = self.action_context.get("action_id")
            if self.stopping:
                raise asyncio.CancelledError()
            checked = {
                "run_command": ("run_command_checked", "workspace_revision"),
                "write_workspace_file": (
                    "write_workspace_file_checked",
                    "file_revision",
                ),
                "browser_open": ("browser_open_scoped", "origin"),
            }.get(name)
            target = method
            if name == "execute_windows":
                if not action_id:
                    raise RuntimeError("Windows mutations require the action dispatcher")
                kwargs["action_id"] = action_id
            if (
                checked
                and self.action_context.get(checked[1])
                and isinstance(self.sandbox, CheckedSandbox)
            ):
                target = getattr(self.sandbox, checked[0])
                kwargs["expected"] = self.action_context[checked[1]]
            token = remote_action_id.set(action_id)
            try:
                task = asyncio.create_task(target(*args, **kwargs))
            finally:
                remote_action_id.reset(token)
            self.pending.add(task)

            def settled(finished):
                self.pending.discard(finished)
                if (
                    not finished.cancelled()
                    and finished.exception() is None
                    and isinstance(finished.result(), CommandResult)
                ):
                    self.last_command = finished.result()

            task.add_done_callback(settled)
            result = await asyncio.shield(task)
            captured = getattr(result, "image", result)
            if getattr(captured, "metadata", None) is not None:
                captured.metadata["action_id"] = action_id
            return result

        return invoke

    async def drain(self):
        self.stopping = True
        if isinstance(self.sandbox, CancellableSandbox):
            await self.sandbox.cancel_commands()
        if self.pending:
            await asyncio.gather(*self.pending, return_exceptions=True)
        if isinstance(self.sandbox, UncertainSandbox) and self.sandbox.uncertain:
            raise TerminationUnverified(
                self.sandbox.uncertain_reason
                or "Windows action outcome unknown; inspect and disconnect before continuing"
            )


