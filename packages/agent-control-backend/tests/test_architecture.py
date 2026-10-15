"""Import and data-access boundaries that the control-plane refactor must keep."""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
KERNEL = ROOT / "packages" / "agentbot" / "src"
CONTROL = ROOT / "packages" / "agent-control-backend" / "src" / "agentbot_control"

# Raw SQL stays in the database layer, the event-store facade, or these modules.
# Shrink this set as call sites move into agentbot_control/repositories.
LEGACY_SQL = {
    "autopilot.py",
    "blob_store.py",
    "compute_profiles.py",
    "computer.py",
    "computer_agents.py",
    "files.py",
    "lifecycle.py",
    "policies.py",
    "terminals.py",
    "tool_libraries.py",
    "transport.py",
}

# Existing transactional operations moved intact into domain modules. Exact paths
# and non-growing call budgets preserve the old boundary without allowing SQL
# throughout a newly introduced package. Repository migration remains separate.
DOMAIN_SQL = {
    "app/__init__.py": 1,
    "app/http.py": 13,
    "approvals/decisions.py": 33,
    "capture_retention/cleanup.py": 26,
    "capture_retention/images.py": 16,
    "capture_retention/policy.py": 12,
    "channels/access.py": 11,
    "channels/admission_ops.py": 38,
    "channels/binding.py": 15,
    "channels/conversation.py": 23,
    "channels/http.py": 9,
    "channels/membership.py": 21,
    "channels/publication.py": 16,
    "channels/scheduling.py": 40,
    "cloud/admission_ops.py": 11,
    "cloud/configuration.py": 14,
    "cloud/http.py": 14,
    "cloud/lifecycle.py": 11,
    "cloud/observations.py": 18,
    "cloud/provisioning.py": 15,
    "cloud/reconciliation.py": 8,
    "cloud/status.py": 8,
    "control/__init__.py": 10,
    "control/input.py": 4,
    "control/leases.py": 21,
    "event_store/__init__.py": 13,
    "event_store/admission_ops.py": 15,
    "event_store/recording.py": 15,
    "event_store/replay.py": 24,
    "groups/__init__.py": 17,
    "groups/handoffs.py": 10,
    "groups/http.py": 21,
    "routines/__init__.py": 20,
    "routines/dispatching.py": 20,
    "routines/http.py": 26,
    "shared_computers/cloud.py": 18,
    "shared_computers/lifecycle.py": 22,
    "shared_computers/resolution.py": 29,
    "shared_computers/settings.py": 6,
    "runtime/__init__.py": 1,
    "runtime/cleanup.py": 6,
    "runtime/execution.py": 3,
    "runtime/lifecycle.py": 9,
    "store/__init__.py": 1,
    "store/bots.py": 7,
    "store/credentials.py": 7,
    "store/identity.py": 6,
    "toolkit/binding.py": 4,
    "toolkit/connectors.py": 6,
    "toolkit/http.py": 25,
    "toolkit/skills.py": 11,
    "windows/enrollment.py": 28,
    "windows/provider.py": 5,
    "workspaces/__init__.py": 15,
    "workspaces/http.py": 49,
}

# Synchronous store.transaction() calls inside async functions. This number may
# only decrease. Database.run() is the replacement.
ASYNC_TRANSACTION_BASELINE = 160


def _py_files(root: Path):
    return [path for path in root.rglob("*.py") if "build" not in path.parts]


def test_kernel_does_not_import_product_packages():
    offenders = []
    for path in _py_files(KERNEL):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            modules = []
            if isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                modules = [node.module]
            if any(
                module.split(".")[0] in {"agentbot_control", "agentbot_tools", "agentbot_windows"}
                for module in modules
            ):
                offenders.append(f"{path.relative_to(ROOT)}:{node.lineno}")
    assert offenders == []


def test_subsystems_do_not_accept_the_runtime_graph():
    offenders = []
    for path in _py_files(CONTROL):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.FunctionDef) and node.name == "__init__":
                arguments = (*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs)
                if any(arg.arg in {"runtime", "services", "coordinator"} for arg in arguments):
                    offenders.append(f"{path.name}:{node.lineno}")
    assert offenders == []


def test_composition_fields_have_concrete_types():
    tree = ast.parse((CONTROL / "composition.py").read_text(encoding="utf-8"))
    services = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.ClassDef) and node.name == "Services"
    )
    fields = [node for node in services.body if isinstance(node, ast.AnnAssign)]
    assert fields
    assert all(ast.unparse(field.annotation) not in {"Any", "object"} for field in fields)


def _uses_sql(path: Path) -> bool:
    text = path.read_text(encoding="utf-8")
    return ".execute(" in text or ".transaction(" in text


def test_raw_sql_stays_in_the_data_layer():
    allowed_roots = {
        CONTROL / "repositories",
        CONTROL / "db.py",
        CONTROL / "event_store.py",
    }
    unexpected = []
    for path in _py_files(CONTROL):
        if not _uses_sql(path):
            continue
        relative = path.relative_to(CONTROL).as_posix()
        if relative in LEGACY_SQL or path == CONTROL / "db.py":
            continue
        if relative in DOMAIN_SQL:
            calls = sum(
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr in {"execute", "transaction"}
                for node in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
            )
            assert calls <= DOMAIN_SQL[relative], f"SQL boundary grew: {relative}"
            continue
        if CONTROL / "repositories" in path.parents:
            continue
        if path in allowed_roots:
            continue
        unexpected.append(str(path.relative_to(CONTROL)))
    assert unexpected == []


def _transaction_calls(node: ast.AST) -> int:
    count = 0
    for child in ast.iter_child_nodes(node):
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        if isinstance(child, ast.With):
            for item in child.items:
                call = item.context_expr
                if (
                    isinstance(call, ast.Call)
                    and isinstance(call.func, ast.Attribute)
                    and call.func.attr == "transaction"
                ):
                    count += 1
        count += _transaction_calls(child)
    return count


def async_transaction_count() -> int:
    total = 0
    for path in _py_files(CONTROL):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.AsyncFunctionDef):
                total += _transaction_calls(node)
    return total


def test_async_transaction_baseline_does_not_grow():
    assert async_transaction_count() <= ASYNC_TRANSACTION_BASELINE
