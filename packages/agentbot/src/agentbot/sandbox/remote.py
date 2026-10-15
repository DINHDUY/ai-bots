"""The existing sandbox services over the authenticated outbound host bridge."""

import uuid
from contextvars import ContextVar

from agentbot.interfaces import ISandboxClient, TerminationUnverified

remote_action_id = ContextVar("remote_action_id", default=None)


class RemoteSandbox(ISandboxClient):
    provider = "azure"

    def __init__(self, binding, call):
        self.binding, self.call = binding, call
        self.session_id = binding["session_id"]
        self.provider = binding["provider"]
        self.uncertain = False
        self.uncertain_reason = ""

    async def rpc(self, method, **arguments):
        from .bridge import mutating

        try:
            return await self.call(
                self.binding,
                method,
                arguments,
                remote_action_id.get() or uuid.uuid4().hex,
            )
        except TerminationUnverified as exc:
            if mutating(method, arguments):
                self.uncertain, self.uncertain_reason = True, str(exc)
            raise

    async def approval_protocol(self):
        return 2

    async def run_bash(self, command):
        return (await self.run_command(command)).text()

    async def run_command(self, command):
        return await self.run_command_checked(command)

    async def run_command_checked(self, command, *, expected=None):
        return await self.rpc("run_command_checked", command=command, expected=expected)

    async def cancel_commands(self):
        await self.rpc("cancel_commands")
        if self.uncertain:
            raise TerminationUnverified(self.uncertain_reason)

    async def browser_click(self, selector):
        return await self.rpc("browser_click", selector=selector)

    async def browser_open(self, url):
        return await self.browser_open_scoped(url)

    async def browser_open_scoped(self, url, *, expected=None):
        return await self.rpc("browser_open_scoped", url=url, expected=expected)

    async def write_workspace_file(self, path, content):
        return await self.write_workspace_file_checked(path, content)

    async def write_workspace_file_checked(self, path, content, *, expected=None):
        return await self.rpc(
            "write_workspace_file_checked",
            path=path,
            content=content,
            expected=expected,
        )

    async def read_workspace_file(self, path):
        return await self.rpc("read_workspace_file", path=path)

    async def list_workspace(self, path):
        return await self.rpc("list_workspace", path=path)

    async def workspace_kind(self, path):
        return await self.rpc("workspace_kind", path=path)

    async def workspace_revision(self):
        return await self.rpc("workspace_revision")

    async def file_revision(self, path):
        return await self.rpc("file_revision", path=path)

    async def capture(self, surface="browser"):
        return await self.rpc("capture", surface=surface)

    async def screenshot(self):
        return await self.capture("desktop")

    async def desktop_action(self, name, params):
        return await self.rpc("desktop_action", name=name, params=params)

    async def human_input(self, surface, event):
        return await self.rpc("human_input", surface=surface, event=event)

    async def service_health(self):
        return await self.rpc("service_health")

    async def files(self, operation, **arguments):
        return await self.rpc("files", operation=operation, **arguments)

    async def terminal(self, operation, **arguments):
        return await self.rpc("terminal", operation=operation, **arguments)

    async def close(self):
        # Host retirement is explicit; this operation never deletes Azure resources.
        return await self.rpc("sandbox.retire")
