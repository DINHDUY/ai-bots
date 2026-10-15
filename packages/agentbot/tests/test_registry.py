import pytest
from agentbot.registry import FrameworkRegistry


class _Adapter:
    async def initialize(self, sandbox, memory_context, state_streamer, instructions: str = "", model=None) -> None:
        return None

    async def execute_step(self, prompt):
        if False:
            yield {}


def test_resolve_is_case_insensitive() -> None:
    registry = FrameworkRegistry()
    registry.register_framework("Microsoft", _Adapter)
    assert isinstance(registry.resolve("MICROSOFT"), _Adapter)


def test_unknown_framework_raises() -> None:
    registry = FrameworkRegistry()
    with pytest.raises(ValueError, match="could not be resolved"):
        registry.resolve("missing")
