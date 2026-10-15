"""Sandbox protocols replace hasattr probes, including Docker uncertainty."""

import pytest
from agentbot.interfaces import TerminationUnverified, UncertainSandbox
from agentbot.sandbox.docker import DockerSandbox
from fakes import MemorySessions


def test_docker_uncertainty_is_a_public_property():
    sandbox = DockerSandbox(container=object(), session_id="s")
    assert isinstance(sandbox, UncertainSandbox)
    assert sandbox.uncertain is False
    sandbox._uncertain = True
    assert sandbox.uncertain is True
    assert "could not be verified" in sandbox.uncertain_reason


def test_memory_sessions_are_not_computer_managers():
    from agentbot.interfaces import SandboxManager

    assert not isinstance(MemorySessions(), SandboxManager)


@pytest.mark.asyncio
async def test_guard_drain_sees_docker_uncertainty():
    from agentbot_control.runtime import GuardedSandbox

    sandbox = DockerSandbox(container=object(), session_id="s")

    async def cancel():
        sandbox._uncertain = True

    sandbox.cancel_commands = cancel  # type: ignore[method-assign]
    with pytest.raises(TerminationUnverified, match="could not be verified"):
        await GuardedSandbox(sandbox).drain()
