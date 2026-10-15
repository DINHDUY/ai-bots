# SRS-009 Validation and quality

Gates a rebuild must pass, and the checks that close each build phase in [000-overview.md](000-overview.md).

## Toolchain

| ID | Requirement |
| --- | --- |
| VAL-001 | Python MUST be 3.11 or 3.13. Node MUST be 24. uv MUST be 0.11.14. Install MUST be `uv sync --locked`. The frontend MUST use `npm ci`. |
| VAL-002 | `make install` MUST install the locked workspace and MUST verify `import agentbot_control.app`. On Linux and macOS the binary directory MUST be selectable with `make BIN=.venv/bin`. |
| VAL-003 | `make env` MUST copy `.env.example` to `.env` and MUST be used only when `.env` is absent or replacement is authorized. Secrets MUST NOT be committed. |
| VAL-004 | The sandbox image MUST be built with `docker build -f docker/sandbox/Dockerfile -t agentbot-sandbox .` Playwright in that image MUST be pinned (the reviewed pin is 1.63.0). A corporate CA MAY be passed as a BuildKit secret and MUST NOT be copied into the image. TLS verification MUST NOT be disabled. |
| VAL-005 | `make check` MUST run, in order: ruff on `packages`, `deploy`, `docs/usecases`, `scripts`, `tests`, and `conftest.py`; `scripts/check_python_size.py`; Pyright; Pyright with `pyrightconfig.foundation.json`; `pytest -m "not docker and not windows_desktop"`; `scripts/docs_check.py`; `scripts/verify_core.py`; `scripts/check_wire.py`; frontend lint, production build, and unit tests. |
| VAL-006 | `make check-docker` MUST run `pytest -m docker --require-docker` and frontend Playwright. Unexpected skips MUST fail the Docker job. |
| VAL-007 | `make hooks` MUST install pre-commit covering ruff, Pyright, line endings, and frontend `tsc`. |
| VAL-008 | CI in `.github/workflows/check.yml` MUST run the unit job on `ubuntu-latest` and `windows-latest` for Python 3.11 and 3.13, plus a required Ubuntu Docker and Playwright job on Python 3.11. `fail-fast` MUST be false. Permissions MUST be contents read. |
| VAL-009 | `make windows-setup`, `make windows-companion`, and `make windows-test` MUST drive the UFO companion. `make azure-install` MUST sync the backend `azure` extra. `make azure-test` MUST run the cloud and computer-agent tests. `make docs-check` MUST run `scripts/docs_check.py`. |
| VAL-010 | Live model calls MUST NOT be part of the default suite. Every model boundary MUST be a protocol with a scripted fake. |

## Size and layout

| ID | Requirement |
| --- | --- |
| VAL-011 | Each Python file MUST stay at or below 500 active lines and SHOULD be split at 450. The split target is 200–400 active lines. Active lines MUST be counted with the AST and tokenizer: exclude blanks, comments, and docstrings; count imports, decorators, continuations, and nonblank lines inside executable strings. A line that mixes a docstring with code counts. Counting MUST happen after Ruff format. |
| VAL-012 | `scripts/check_python_size.py` and `tests/test_repository_rules.py` MUST fail `make check` and CI on a violation. Compressing statements or hiding code in strings to pass the counter MUST NOT be done. |
| VAL-013 | After `ruff check --fix` and `ruff format`, the author MUST review the diff, recount sizes, and retest. Assertions MUST NOT be weakened and tests MUST NOT be skipped to obtain a pass. |
| VAL-014 | `scripts/docs_check.py` MUST resolve relative Markdown links outside fenced code and MUST fail when the capability table in the blueprint drifts from `docs/capabilities.json`. |
| VAL-015 | `scripts/verify_core.py` MUST prove the core wheel installs without product dependencies. `scripts/check_wire.py` MUST reject schema drift. |

## Test layers

| ID | Layer | What it must prove |
| --- | --- | --- |
| VAL-016 | Kernel | Adapter resolution, busy guard, atomic memory save, idle close, frame shapes, approval timeout equals deny. Fakes: `FakeSandbox`, `MemorySessions`. |
| VAL-017 | Adapters | Tool mapping, approval gating, batch halt, denial, step caps, provider checks, Foundry base URL. Scripted client or injected runner. |
| VAL-018 | Desktop planner | All 17 actions, every bound and rejection, no display required. |
| VAL-019 | Path jail | Traversal, backslashes, absolute paths, and root handling. |
| VAL-020 | Docker | `run_bash`, workspace write and read, jail rejection of `/etc/passwd`, screenshot PNG, and the computer-service suite (browser, files, symlink rejection, hibernate, PTY). `SANDBOX_IMAGE` MAY select an alternate image. |
| VAL-021 | Control plane | Register and login, cross-user 404s, credentials, runtime recovery, kernel import boundary, SQL placement, and a non-increasing count of synchronous `transaction()` calls inside `async def`. |
| VAL-022 | Frontend | Reducer transitions, presentation rules, navigation without reconnecting, approvals, capture history, interruption, responsive layout at the four viewports in `FE-019`. |
| VAL-023 | Windows | Companion job probe and native probe via `make windows-test`. Interactive qualification requires an unlocked desktop. |
| VAL-024 | Acceptance | `behave` runs `docs/usecases/tests/behavior/azure-blob-etl.feature` when Docker, the sandbox image, and local Azurite are present. The product packages MUST NOT contain the ETL implementation. |

## Phase acceptance

Do not start the next phase until these pass.

| Phase | Checks |
| --- | --- |
| 1 | Frame shapes and approval timeout are tested. |
| 2 | Busy guard, memory round trip, atomic save, and idle sweep pass with fakes. |
| 3 | Planner and path-jail unit tests pass. Docker-marked tests pass. The container runs as uid 1000 with dropped capabilities and the CMP-004 limits. |
| 4 | Scripted Anthropic tests cover every tool and the batch-halt path. |
| 5 | Scripted Microsoft tests pass on the same kernel and the same frame types. |
| 6 | Gateway tests pass. The gateway binds localhost and is not started with the control plane. |
| 7 | Cross-tenant 404 on every route. Origin and cookie startup checks hold. Secrets never appear in responses. |
| 8 | Reducer unit tests, MSW tests, and Playwright at four viewports pass. Routes do not start runs. |
| 9 | Refresh during a run recovers state. Duplicate starts create one run. Restart yields `interrupted` and never re-executes. Foreign access fails on HTTP and WebSocket. |
| 10 | Policy match, revocation, deadline races, and Autopilot fencing pass, including a real Docker case that creates a file unattended and then requires a manual gate after Autopilot is turned off. |
| 11 | Inspect-only health, revision-bound download, fenced human input, PTY cleanup, and hibernate/resume pass against the real image. |
| 12 | Roles, shares, groups, and channel limits pass. A URL alone does not authorize a share. |
| 13 | Tool pin and removal fences, skill drift stop, GitHub revoke, routine restart recovery, and webhook dedupe pass. |
| 14 | UFO text and planner probes pass on an unlocked desktop. Azure tests pass with a mocked driver unless a live subscription is configured. Cloud selection does not fall back to Docker. |
| 15 | Retention cleanup order and 404s for expired captures pass. Shared-computer mode refuses a switch while a computer is open and keeps Windows bots isolated. |
| 16 | `GET /ready` stays 503 until workers progress. Backup of a stopped database plus blobs verifies in a fenced directory. Key rotation dry-run reports zero candidates after a successful rotate. |

## Demo contract

The Azure Blob ETL playbook is optional and lives only under `docs/usecases`. If the behave feature is implemented, it MUST keep these outcomes:

| ID | Requirement |
| --- | --- |
| VAL-025 | The sandbox has Python 3 and bash and does not have the Azure SDK or Azure CLI. SAS values MUST be written only to `/workspace/azure.env`, MUST NOT be printed, and MUST NOT appear on a command line. |
| VAL-026 | The approval order MUST be write `azure.env`, write `etl_orders.py`, then bash `python3 /workspace/etl_orders.py`. A bash detail that contains a SAS token MUST be denied. A denial MUST return `User denied this action.` and MUST NOT publish curated blobs. |
| VAL-027 | A missing source blob MUST surface HTTP 404 and MUST NOT publish curated blobs. A bash timeout MUST contain `bash error: command timed out after 30s.` Close MUST remove the container and MUST keep the bot and transcript. A later turn MUST reuse the container. |

## Release evidence

| ID | Requirement |
| --- | --- |
| VAL-028 | Release A (phases 1–11 through files) MUST show reconnect recovery, scoped approvals, inspected computer status, and revision-bound downloads. |
| VAL-029 | Release B (human control, PTY, lifecycle) MUST show on real Docker that human and agent writers are exclusive and that each lifecycle command has its advertised effect. |
| VAL-030 | Release C (workspaces through routines) MUST show that each workflow survives refresh, uses current permissions, and goes through the same coordinator and approval path. |
| VAL-031 | Local tests MUST be labeled as collection, mocked, local, CI, or live-provider evidence. A green local suite MUST NOT be reported as hosted CI or as a live Azure or GitHub run. |
| VAL-032 | Ordinary pytest MUST deselect Docker and Windows-desktop marks. The command is `pytest -m "not docker and not windows_desktop"`. |

## Traceability

| IDs | Sources |
| --- | --- |
| VAL-001–VAL-010 | [Makefile](../../Makefile); [.github/workflows/check.yml](../../.github/workflows/check.yml); [021](../021-foundation-operations.md); ADR-0015 |
| VAL-011–VAL-015 | [AGENTS.md](../../AGENTS.md); [022](../022-python-size-refactoring-plan.md) |
| VAL-016–VAL-024 | Blueprint §13.2; [003](../003-agent-control-implementation-status.md) |
| Phase table | Blueprint §14; [018](../018-agent-control-backend-features-plan.md) |
| VAL-025–VAL-027 | [azure-blob-etl-playbook.md](../usecases/azure-blob-etl-playbook.md) |
| VAL-028–VAL-032 | [018](../018-agent-control-backend-features-plan.md); [003](../003-agent-control-implementation-status.md) |
