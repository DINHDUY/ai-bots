# AI coding agent instructions

Applies throughout this repository; read additional local instructions before editing.

## Ownership and workflow

- AI coding agents build and maintain the repository, including design, implementation, debugging, tests, documentation, dependencies, CI, and authorized operations.
- Humans provide ideas and priorities, review results, and approve plans; do not leave engineering work to humans.
- Inspect the working tree and preserve unrelated edits, configuration, and services.
- Obtain approval for substantial new plans or material scope changes. A direct change request or approved plan already authorizes its scope; do not repeatedly ask for approval.
- Execute approved work through validation and documentation. Record decisions and remaining work for the next agent; never claim an incomplete milestone is complete.
- Read README.md, docs/003-agent-control-implementation-status.md, and the applicable approved plan before implementation.

## Architecture

- Never exceed 500 active lines per Python file. Proactively split at 450 into logical submodules in the same domain directory; target 200-400 lines after formatting.
- Use scripts/check_python_size.py for active-line counting: exclude blanks, comments, and docstrings; count executable multiline strings. Do not compress statements or hide code to evade limits.
- Organize by flat feature/domain packages. Use absolute package imports, explicit exports, and narrow typed dependencies; avoid nested controllers/services hierarchies and dynamic method grafting.
- Tests and test helpers must stay outside production source: use package tests/ directories, frontend tests/ or e2e/, and docs/usecases/tests/ for demos. Never co-locate tests in src/.
- Keep the kernel independent of backend/product tools. Keep demos, including ETL instructions, outside backend and frontend product behavior.
- Preserve server-owned execution, durable requests, atomic state/event updates, leases, permissions, and action-specific approvals. Reconcile uncertain side effects before retrying.
- Use persistence boundaries and keep blocking work off the event loop; cancellation does not prove rollback. Preserve the single-control-process SQLite model.
- Preserve protocol v2 validation and regenerate derived contracts from their source. Follow docs/021-foundation-operations.md for recovery and key rotation.

## Validation and completion

- Use Makefile and .github/workflows/check.yml for locked installs, supported environments, and required gates. On Linux/macOS use make BIN=.venv/bin <target>.
- After code changes run the project pytest suite in the workspace environment, plus applicable make check, make check-docker, make windows-test, and demo/frontend checks.
- Run ruff check --fix and ruff format on changed Python files, review automated edits, recount sizes, and retest before completion.
- Diagnose terminal errors and fix syntax, typing, lint, and test failures autonomously. Do not weaken checks, remove assertions, or hide skips to get a passing result.
- For documentation-only work, verify accuracy, links, and whitespace; run make docs-check when applicable.
- Report commands actually run, outcomes, and unresolved gaps. Distinguish collection, mocked, local, CI, and live-provider evidence.
- Never expose or commit secrets. make env overwrites .env; use only when absent or replacement is authorized.
- Publishing, deployment, destructive operations, and external communications require authorization covering the action.
