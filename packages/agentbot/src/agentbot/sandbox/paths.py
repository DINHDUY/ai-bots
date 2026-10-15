"""Workspace path checks shared by every sandbox driver."""

from __future__ import annotations

from urllib.parse import urlparse

WORKSPACE_ROOT = "/workspace"


class WorkspacePathError(PermissionError):
    """A path escaped the workspace root."""


def resolve_workspace_path(path: str, *, allow_root: bool = False) -> str:
    """Normalize ``path`` and require it to stay under ``/workspace``."""

    raw = (path or "").strip().replace("\\", "/")
    if not raw or raw == ".":
        if allow_root:
            return WORKSPACE_ROOT
        raise WorkspacePathError("A workspace path is required.")

    if raw.startswith("/"):
        if raw != WORKSPACE_ROOT and not raw.startswith(WORKSPACE_ROOT + "/"):
            raise WorkspacePathError(path)
        candidate = raw
    else:
        relative = raw
        while relative.startswith("./"):
            relative = relative[2:]
        candidate = f"{WORKSPACE_ROOT}/{relative.lstrip('/')}"

    parts: list[str] = []
    for part in candidate.split("/"):
        if part in ("", "."):
            continue
        if part == "..":
            if parts:
                parts.pop()
            continue
        parts.append(part)

    normalized = "/" + "/".join(parts)
    if normalized != WORKSPACE_ROOT and not normalized.startswith(WORKSPACE_ROOT + "/"):
        raise WorkspacePathError(path)
    if normalized == WORKSPACE_ROOT and not allow_root:
        raise WorkspacePathError("A file path inside the workspace is required.")
    return normalized


def validate_http_url(url: str) -> str:
    """Allow only absolute http and https URLs."""

    parsed = urlparse(url.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise PermissionError(f"Only http and https URLs are allowed: {url}")
    return url.strip()
