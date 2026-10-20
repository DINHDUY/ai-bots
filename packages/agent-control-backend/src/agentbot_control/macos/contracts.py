"""Side-effect-free source of macOS HTTP and companion contracts."""

from typing import Literal

from agentbot_macos.actions import MacAction, Permit
from agentbot_macos.protocol import Hello, Strict
from agentbot_macos.results import TaskReceipt
from agentbot_macos.taskstar import TaskAssignment

from agentbot_control.macos.schemas import CompleteEnrollment, SelectComputer, Takeover


class PublicMacState(Strict):
    protocol: Literal[1]
    name: str
    revision: int
    sharing: bool
    armed: bool
    ready: bool
    screen_recording: bool
    accessibility: bool
    reason: str
    oi_revision: str
    patch_version: int
    scope: Literal["window", "display"]


class MacDevice(Strict):
    id: str
    name: str
    provider: Literal["macos_local"]
    revoked: bool
    online: bool
    state: PublicMacState | None


class MacDeviceList(Strict):
    computers: list[MacDevice]


class MacContracts(Strict):
    assignment: TaskAssignment
    action: MacAction
    permit: Permit
    hello: Hello
    enrollment: CompleteEnrollment
    selection: SelectComputer
    takeover: Takeover
    devices: MacDeviceList
    receipt: TaskReceipt
