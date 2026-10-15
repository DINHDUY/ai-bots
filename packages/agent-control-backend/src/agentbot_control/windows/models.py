from __future__ import annotations

import hashlib

from pydantic import Field

from agentbot_control.schemas import Command


def token_hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


class Enrollment(Command):
    pass


class Takeover(Command):
    generation: int = Field(ge=1)


class CompleteEnrollment(Command):
    code: str = Field(min_length=32, max_length=200)
    name: str = Field(min_length=1, max_length=100)


class SelectComputer(Command):
    device_id: str = Field(min_length=8, max_length=100)
    expected_revision: int = Field(ge=0)
