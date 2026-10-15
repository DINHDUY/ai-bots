from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


EXAMPLE = ROOT / "deploy" / "azure" / "compute-profiles.example.json"


DEFAULT_OUTPUT = ROOT / "deploy" / "azure" / "compute-profiles.json"


ATTACH = ["attach", "start", "stop", "reset", "close"]


VNET_PREFIX = "10.20.0.0/16"


SUBNET_PREFIX = "10.20.0.0/24"


IMAGE_PUBLISHER = "Canonical"


IMAGE_OFFER = "ubuntu-24_04-lts"


IMAGE_SKU = "server"


ADMIN_USERNAME = "agentcontrol"


ENV_KEY = "CONTROL_COMPUTE_PROFILES"


WORKSPACE_TAG = "agentcontrol-workspace-id"


SANDBOX_REPOSITORY = "agentbot-sandbox"


USERNAME = re.compile(r"^[A-Za-z0-9_-]{3,32}$")
