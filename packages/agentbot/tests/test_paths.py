import pytest
from agentbot.sandbox.paths import WorkspacePathError, resolve_workspace_path, validate_http_url


def test_relative_path_stays_in_workspace() -> None:
    assert resolve_workspace_path("src/app.py") == "/workspace/src/app.py"


def test_parent_segments_cannot_escape() -> None:
    with pytest.raises(WorkspacePathError):
        resolve_workspace_path("foo/../../etc/passwd")
    with pytest.raises(WorkspacePathError):
        resolve_workspace_path("../etc/passwd")


def test_absolute_path_outside_workspace_is_rejected() -> None:
    with pytest.raises(WorkspacePathError):
        resolve_workspace_path("/etc/passwd")


def test_workspace_root_requires_allow_root() -> None:
    with pytest.raises(WorkspacePathError):
        resolve_workspace_path(".")
    assert resolve_workspace_path(".", allow_root=True) == "/workspace"


def test_http_url_policy() -> None:
    assert validate_http_url("https://example.com/a") == "https://example.com/a"
    with pytest.raises(PermissionError):
        validate_http_url("file:///etc/passwd")
    with pytest.raises(PermissionError):
        validate_http_url("javascript:alert(1)")
