"""Strict HTTP contracts for macOS device enrollment and selection."""

from agentbot_macos.protocol import Strict
from pydantic import Field

from agentbot_control.schemas import Command


class CompleteEnrollment(Strict):
    code: str = Field(min_length=20, max_length=128)
    name: str = Field(min_length=1, max_length=100)


class SelectComputer(Command):
    device_id: str = Field(min_length=1, max_length=128)
    expected_revision: int = Field(ge=0)


class Takeover(Command):
    generation: int = Field(ge=1)
