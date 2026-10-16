"""Caller-supplied model credentials. None at the kernel means use process env."""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlparse

PROVIDERS = frozenset({"openai", "anthropic", "azure_foundry"})
_MODEL = re.compile(r"^[A-Za-z0-9._:/-]{1,128}$")


def providers_for_framework(framework: str) -> frozenset[str] | None:
    """Providers a framework may use. None means the framework does not constrain them."""

    if framework == "anthropic":
        return frozenset({"anthropic"})
    if framework in {"microsoft", "ufo", "open_interface"}:
        return frozenset({"openai", "azure_foundry"})
    return None


def validate_foundry_endpoint(endpoint: str) -> str:
    """Accept an https Foundry base URL and reject embedded credentials."""

    text = endpoint.strip()
    parsed = urlparse(text)
    if parsed.scheme != "https" or not parsed.hostname:
        raise ValueError("Foundry endpoint must be an https URL.")
    if parsed.username or parsed.password:
        raise ValueError("Foundry endpoint must not include credentials.")
    if parsed.query or parsed.fragment:
        raise ValueError("Foundry endpoint must not include a query or fragment.")
    return text.rstrip("/")


@dataclass(frozen=True)
class ModelConfig:
    """One user's key, model id, and optional Foundry base URL."""

    provider: str
    api_key: str
    model: str
    endpoint: str = ""

    def __post_init__(self) -> None:
        provider = self.provider.strip()
        if provider not in PROVIDERS:
            raise ValueError(f"Unknown provider '{self.provider}'.")
        key = self.api_key.strip()
        if len(key) < 8 or len(key) > 4096 or any(char in key for char in "\r\n"):
            raise ValueError("API key must be 8-4096 characters on one line.")
        model = self.model.strip()
        if not _MODEL.fullmatch(model):
            raise ValueError("Model must be 1-128 characters of letters, digits, or . _ : / -.")
        endpoint = self.endpoint.strip()
        if provider == "azure_foundry":
            endpoint = validate_foundry_endpoint(endpoint)
        elif endpoint:
            raise ValueError("Only an azure_foundry credential uses an endpoint.")
        object.__setattr__(self, "provider", provider)
        object.__setattr__(self, "api_key", key)
        object.__setattr__(self, "model", model)
        object.__setattr__(self, "endpoint", endpoint)
