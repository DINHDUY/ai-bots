"""Optional provider composition; importing the kernel never imports web or SDKs."""

import os
from pathlib import Path

from agentbot.kernel import EngineRuntimeManager, SessionStore
from agentbot.registry import FrameworkRegistry


def build_kernel(*, control: bool = False) -> EngineRuntimeManager:
    try:
        from agentbot.adapters.anthropic import ClaudeAgentAdapter
        from agentbot.adapters.microsoft import MicrosoftAgentAdapter
        from agentbot.sandbox.docker import DockerSessionManager
    except ImportError as exc:
        raise RuntimeError("Install agentbot[docker,anthropic,microsoft] for the default runtime.") from exc
    registry = FrameworkRegistry()
    registry.register_framework("microsoft", MicrosoftAgentAdapter)
    registry.register_framework("anthropic", ClaudeAgentAdapter)
    data_dir = Path(os.environ.get("SESSION_DATA_DIR", "data/sessions"))
    return EngineRuntimeManager(
        registry=registry,
        sandboxes=DockerSessionManager(image=os.environ.get("SANDBOX_IMAGE", "agentbot-sandbox")),
        sessions=SessionStore(data_dir if control else data_dir / "gateway"),
    )

