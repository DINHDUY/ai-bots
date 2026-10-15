"""Create tool access for the product catalog."""

from agentbot.tools.context import ToolAccess

from agentbot_tools.registry import REGISTRY


def access(bindings, *, validate=None):
    return ToolAccess(
        bindings,
        validate=validate,
        registry=REGISTRY,
    )
