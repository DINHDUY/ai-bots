"""Tool names that already belong to a native bundle or peer operation."""

from __future__ import annotations


def reserved_tool_ids() -> frozenset[str]:
    from agentbot.adapters.anthropic.constants import BASH_NAME, EDITOR_NAME
    from agentbot.sandbox.desktop_plan import COMPUTER_ACTIONS

    from agentbot_tools.messaging import peer_schemas

    return frozenset(
        {
            BASH_NAME,
            EDITOR_NAME,
            *COMPUTER_ACTIONS,
            *(item["name"] for item in peer_schemas()),
        }
    )
