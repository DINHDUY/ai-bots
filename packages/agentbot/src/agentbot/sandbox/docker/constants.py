from __future__ import annotations

import logging

logger = logging.getLogger("AgentBotKernel")


STDOUT_CAP = 16_000


LABEL = "agentbot.session_id"


DESKTOP_SCRIPT = "/opt/agentbot_sandbox/desktop.py"


BROWSER_CTL = "/opt/agentbot_sandbox/browserctl.py"


COMMAND_SCRIPT = "/opt/agentbot_sandbox/command.py"
