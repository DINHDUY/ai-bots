"""Adapter package."""

from agentbot.adapters.anthropic import ClaudeAgentAdapter
from agentbot.adapters.microsoft import MicrosoftAgentAdapter

__all__ = ["ClaudeAgentAdapter", "MicrosoftAgentAdapter"]
