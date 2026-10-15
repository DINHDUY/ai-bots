# Python file-size and test-separation refactoring plan

Status: R0-R6 implemented; R7 checks pass except the final native desktop retry,
which requires an unlocked Windows desktop. See the [validation record](metrics/python-size-refactoring.md).
Audit date: 2026-10-09. Baseline: `839b6bbfd72608a7011176a9e45668ba9f25e07e`.

## Implementation results

| Stage | Result |
| --- | --- |
| R0 | Restored 34-line agent instructions; recorded baseline sizes, 436 passing cases, schemas and warning counts; added tested size/location rules. |
| R1 | Extracted shared test support, split oversized tests, and moved 15 frontend tests plus the Behave harness outside source. All original cases are accounted for. |
| R2 | Split Docker, Anthropic and Windows integration modules while retaining imports and optional dependency boundaries. |
| R3 | Split Catalog, EventStore, approvals and retention; preserved database/transaction ownership and bounded SQL guards. |
| R4 | Split workspaces, groups, routines, toolkit and control into feature packages with separate HTTP registration. |
| R5 | Split app, runtime, channels and cloud; preserved schemas, phase ordering, recovery and cancellation behavior. |
| R6 | Split Azure deployment tooling; verified CLI/import compatibility and all five installed wheels. All 272 Python files are below 450 active lines. |
| R7 | Local Python matrix, Docker, frontend, browser, demo, static and documentation checks pass. Final interactive native retry awaits desktop unlock; R1 native qualification passed. |

The [validation record](metrics/python-size-refactoring.md) and
[inventory/test mapping](metrics/python-size-refactoring.json) contain the measured
results and remaining environment requirement. No application feature changes or
database migrations were introduced.

## Objective and boundaries

Bring every repository-owned Python file within the 500-active-line maximum,
proactively split files approaching 450 lines, and keep all tests outside production
source directories. Preserve all features and make every required test suite pass.

AI coding agents own implementation, validation, documentation, and failure diagnosis.
Humans review and approve this plan and any material change to its scope.

This is a structural refactor. Preserve HTTP and WebSocket contracts, CLI commands,
public Python imports, configuration defaults, database schemas, transaction boundaries,
event ordering, approvals, retries, cancellation, authorization, and provider behavior.
Do not bundle dependency upgrades, new features, schema migrations, changes to recovery
policy, or completion of unrelated foundation milestones into these changes.

The test-separation requirement applies to Python and frontend tests. It supersedes
the earlier instruction to co-locate tests. At audit time there was no root
`AGENTS.md`; the first implementation step must restore/update it with the approved
rules, keeping it under 50 lines. Files kept under `.git` are not project guidance
to publish or modify.

## Counting and enforcement contract

- Scope: all repository-owned `.py` files, including source, tests, test helpers,
  deployment scripts, sandbox code, demos, and the checker itself. Scan tracked files
  and non-ignored new files; exclude dependencies, virtual environments, caches,
  build output, and third-party checkout data. Do not exempt a maintained file merely
  by calling it generated or moving it outside `packages`.
- Define an active line as a physical line containing a Python code token. Exclude
  blank lines, comment-only lines, and actual module/class/function docstrings
  identified by AST position. Count imports, decorators, continuation lines, and
  nonblank lines inside executable strings such as SQL or embedded scripts.
  A line containing both a docstring and other code still counts.
- Use Python AST and tokenization, not a comment-stripping regex. Count source after
  Ruff formatting. Report both active and total physical lines.
- Hard maximum: 500 active lines. Proactive split threshold: 450. Aim for 200-400
  active lines per extracted module; final acceptance requires every file below 450,
  so none remains at the proactive threshold.
- Do not meet the limit by removing useful comments, packing statements onto one line,
  hiding executable code in strings, or moving an oversized class into another file.
  Split responsibilities while preserving behavior.
- Add one reusable checker, proposed as `scripts/check_python_size.py`, and separate
  tests under `tests/test_repository_rules.py`; register the new test root in pytest.
  Test exact boundary values, docstrings/comments, multiline strings, executable
  docstring lines, CRLF/encoding handling, nested packages, and new-file discovery.
- Integrate size and test-location checks into `make check` and CI. Fail for Python
  test modules/helpers under production source roots and frontend tests/test-support
  under `src`. Reject production imports of test support. Keep the root pytest
  `conftest.py` collection hook outside application source.
- During staged implementation, use the recorded inventory as a temporary,
  non-growing exception list for existing oversized files only. New/refactored files
  must stay below 450. Remove entries as each file is split; final enforcement has
  no exceptions and must not silently fall back to report-only mode.

## Measured inventory

The audit parsed **185 Python files**: **18 exceed 500 active lines**
(16 application/tooling/harness files and two test files), and **three more have
450-500 active lines**. Six additional files have 400-449 active lines.
No Python test modules were found under package `src` trees.

The frontend has **15 test files** under `src`, plus
`src/test/setup.ts`, `src/test/fakeSocket.ts`, and `src/test/server.ts`.
These must move to its separate `tests` tree. Existing `e2e` tests already have
their own directory.

The table includes every file at or above the proactive threshold. Proposed splits
are responsibilities, not a requirement to create one file for every noun; measure
each resulting module after formatting.

| Current file | Active | Physical | Proposed split |
| --- | ---: | ---: | --- |
| `packages/agent-control-backend/src/agentbot_control/channels.py` | 1860 | 1956 | Channel models, membership/access, messages/artifacts, delivery, scheduling, HTTP registration, and bounded persistence modules. |
| `packages/agent-control-backend/src/agentbot_control/cloud.py` | 1515 | 1605 | Configuration/admission, operation state, reconcile steps, cleanup, provider routing, HTTP registration, and persistence. |
| `deploy/azure-infra.py` | 848 | 947 | Keep the CLI entry point; extract Azure command execution, discovery/images, network/compute provisioning, and profile/environment output into a deployment-domain package. |
| `packages/agent-control-backend/src/agentbot_control/routines.py` | 740 | 783 | Definition/schedule calculation, admission/dispatch, ticking, HTTP registration, and persistence. |
| `packages/agent-control-backend/src/agentbot_control/runtime.py` | 698 | 731 | Keep Runtime as the public coordinator; extract startup/recovery, run execution, and stop/close/sweep responsibilities. |
| `packages/agent-control-backend/src/agentbot_control/toolkit.py` | 672 | 731 | Recording, skill replay, connector execution, HTTP registration, and persistence. |
| `packages/agent-control-backend/tests/test_channels.py` | 667 | 719 | Split access/configuration, messages/artifacts, delivery/recovery, and computer/approval scenarios; extract shared helpers. |
| `docs/usecases/steps/support.py` | 632 | 744 | Split the Behave harness into scripted model fixtures, gateway driver, blob/proxy fixtures, and container/lifecycle support within the separate demo test tree. |
| `packages/agent-control-backend/src/agentbot_control/control.py` | 615 | 653 | Lease acquisition/renewal, input dispatch, release/resume, HTTP registration, and persistence. |
| `packages/agent-control-backend/src/agentbot_control/event_store.py` | 586 | 630 | Keep the EventStore API; extract admission/receipts, frame/capture writes, snapshots/recovery, using the existing transaction and repository boundaries. |
| `packages/agent-control-backend/src/agentbot_control/windows.py` | 578 | 644 | Separate connection/RPC, enrollment/HTTP, WindowsSandbox, and ProviderRouter without changing pairing or fencing. |
| `packages/agent-control-backend/src/agentbot_control/app.py` | 565 | 641 | Keep create_app/main and public helpers; separate environment/bootstrap configuration and route registration by feature. |
| `packages/agent-control-backend/tests/test_autopilot.py` | 565 | 617 | Split permissions/receipts, decision races, lifecycle/recovery, routines/groups, and Docker integration; extract helpers. |
| `packages/agentbot/src/agentbot/sandbox/docker.py` | 561 | 630 | Separate DockerSandbox operations from DockerSessionManager lifecycle; keep exports and optional Docker imports compatible. |
| `packages/agent-control-backend/src/agentbot_control/workspaces.py` | 549 | 609 | Separate membership/grants, sharing/preferences/search, HTTP registration, and persistence. |
| `packages/agent-control-backend/src/agentbot_control/capture_retention.py` | 546 | 588 | Separate policy/selection, image storage/history, deletion/recovery, and sweep orchestration. |
| `packages/agent-control-backend/src/agentbot_control/approvals.py` | 541 | 576 | Separate Approvals persistence/decisions from ActionArbiter dispatch and context validation. |
| `packages/agent-control-backend/src/agentbot_control/store.py` | 535 | 613 | Keep Catalog and public types; extract validation/serialization, identity/session, credential, and bot persistence responsibilities. |
| `packages/agentbot/src/agentbot/adapters/anthropic.py` | 491 | 544 | Separate message client/response conversion from adapter execution and tool dispatch; preserve tool ordering and telemetry. |
| `packages/agent-control-backend/src/agentbot_control/groups.py` | 471 | 497 | Separate definitions/routes from admission/handoff orchestration and persistence. |
| `packages/agent-control-backend/tests/test_workspace_services.py` | 460 | 498 | Extract LiveSandbox/LiveManager and helpers; split control/capture, workspace access/sharing, groups, and routines. |

Proactive watch list:

| Current file | Active | Treatment |
| --- | ---: | --- |
| `packages/agent-control-backend/tests/test_cloud.py` | 446 | Split proactively with test support work; already close to 450. |
| `packages/agentbot-windows-companion/tests/native_probe.py` | 443 | Split proactively with test support work; already close to 450. |
| `packages/agent-control-backend/src/agentbot_control/computer_agents.py` | 432 | Recount after formatting/import changes; split if projected size reaches 450. |
| `packages/agentbot-windows-companion/src/agentbot_windows/native.py` | 420 | Recount after formatting/import changes; split if projected size reaches 450. |
| `packages/agent-control-backend/tests/test_approvals.py` | 415 | Recount after formatting/import changes; split if projected size reaches 450. |
| `packages/agent-control-backend/src/agentbot_control/providers/azure.py` | 414 | Recount after formatting/import changes; split if projected size reaches 450. |

Recompute the entire inventory at implementation start and after each stage.
Formatting and extracted imports can make a previously compliant file cross the
threshold; the initial list is not the final scope of the checker.

## Module layout and compatibility

Use a flat feature/domain package when a module needs several collaborators.
For example, `agentbot_control/channels.py` may become
`agentbot_control/channels/` containing `__init__.py`, `models.py`,
`membership.py`, `messages.py`, `delivery.py`, `scheduling.py`, `http.py`,
and appropriately sized persistence modules. Keep submodules in that domain
directory; do not introduce nested `controllers/services/managers` hierarchies.

Preserve imports such as `from agentbot_control.channels import Channels` with
explicit exports. Do not leave both `channels.py` and `channels/` competing for
the same import name. Use absolute package imports and one-way internal dependencies:
models and narrow protocols first, concrete collaborators next, public composition
last. Internal modules should not import their own re-exporting facade.

Use composition with explicit state/callback dependencies. Do not introduce dynamic
method grafting, an untyped context object, or a large mixin hierarchy to distribute
one oversized class. Preserve constructor signatures and observable ownership of
mutable state, locks, tasks, caches, connections, and cleanup.

SQL requires special treatment: `test_architecture.py` currently recognizes
`repositories/` and legacy module filenames. Reuse existing repositories where
possible. If extracted domain SQL needs new files, identify exact domain persistence
paths as data-layer modules in the architecture guard and remove corresponding
legacy allowances as the move completes. Do not broadly allow SQL anywhere in a
domain or add new business modules to `LEGACY_SQL`. Persistence helpers must receive
the existing transaction/connection; this plan does not change connection ownership,
offloading, atomicity, or transaction timing. Keep the async-transaction ceiling
non-increasing and ensure the recursive guard scans every new module.

Before changing module paths, inventory public exports, test patch targets,
Pydantic/OpenAPI names, `__file__` resource lookups, CLI entry points, worker launches,
tool manifest inputs, and wheel contents. Preserve existing dependency-injection
seams, including patches of `agentbot_control.app.build_kernel`. Structural moves
must not invalidate saved tool bindings or alter runtime defaults.

## Test layout

- Python tests stay in `packages/<distribution>/tests/`; use domain-specific test
  filenames or shallow domain folders there. Keep helpers in that test tree and
  preserve unique import names across packages.
- Extract shared fixtures/builders from `test_control.py`, `test_runtime.py`,
  `test_approvals.py`, `test_workspace_services.py`, `test_autopilot.py`, and
  `test_automation.py` before splitting consumers. Replace cross-test imports with
  dedicated support imports; fixtures must retain their scopes and cleanup behavior.
- Move frontend unit tests to `packages/agent-control-frontend/tests/`, grouped by
  feature, and test support to `tests/support/`. Preserve `e2e/`. Update Vitest
  discovery/setup paths, test/mock imports, TypeScript includes, and the npm lint
  command (currently `eslint src e2e`) so moved tests remain tested, typed, and linted.
- Keep standalone demo implementation in `docs/usecases/`. Move Behave features,
  `environment.py`, step definitions, and harness support into
  `docs/usecases/tests/behavior/`; update `behave.ini`, lifecycle imports, resource
  paths, and documentation links. Keep demo pytest tests under `docs/usecases/tests/`.
  Do not register or package demo helpers as product tools.
- Preserve native qualification scripts in the Windows companion's `tests/` tree.
  If `native_probe.py` is split, keep its script entry point and qualify direct
  script execution as well as imports.
- Record old-to-new test node IDs when files move. Preserve test functions,
  parameter combinations, assertions, markers, and fixture lifetimes. No deleted,
  silently uncollected, duplicated, newly skipped, or newly xfailed tests.

## Delivery stages

### R0. Establish a trustworthy baseline

1. Restore/update the root agent instructions with separate test directories.
2. Record the revision, dirty-tree state, full size inventory, supported tool
   versions, test node IDs/markers, warning baseline, public imports, OpenAPI,
   replay schemas, and relevant CLI help.
3. Run the existing validation matrix before refactoring. Investigate failures and
   environmental gaps before attributing them to code moves; isolate any required
   pre-existing bug fix from the behavior-preserving refactor.
4. Establish the size/location checker and its regression tests. Start the temporary
   migration exception list using actual counts, never a blanket exclusion.

Exit: reproducible baseline, explicit test mapping, and automated regression checks.

### R1. Separate and stabilize test infrastructure

1. Extract cross-imported Python helpers, preserving fixture scopes and monkeypatch
   seams. Keep test support out of installed application distributions.
2. Split `test_channels.py`, `test_autopilot.py`, and
   `test_workspace_services.py`; proactively split `test_cloud.py` (446) and
   `native_probe.py` (443).
3. Move the 15 frontend tests and three support files, updating all discovery,
   TypeScript, lint, mock, and setup references in the same change.
4. Move and split the Behave harness and update its configuration/resource paths.

Exit: separate test trees, preserved collection/parameterization, passing Python,
frontend, native-probe, and Behave checks for the moved material.

### R2. Extract bounded kernel and provider modules

1. Split Docker sandbox operations from session lifecycle.
2. Split the Anthropic client/response conversion from execution/tool handling.
3. Split backend Windows connection, enrollment, sandbox, and provider routing.

Exit: stable public imports and optional extras; adapter, Docker, bridge, Windows,
and native qualification checks pass without changed protocol payloads.

### R3. Extract persistence and approval responsibilities

1. Split Catalog validation/serialization and identity/credential/bot persistence.
2. Split EventStore admission, event/capture writes, and replay/recovery helpers.
3. Separate ActionArbiter from approval persistence and decision handling.
4. Split capture-retention policy, storage/history, and deletion/recovery.

Exit: transaction, receipt, approval, replay, encryption, backup/restore, and
retention regressions pass. No schema change, new transaction boundary, or new
async blocking pattern; all architecture guards remain effective.

### R4. Split backend feature orchestration and HTTP registration

Refactor workspaces, groups, routines, toolkit, and human control, one feature at a
time. Extract routes and models first, then narrowly bounded execution/persistence
collaborators as required by measured size. Preserve route registration order,
dependency checks, validation errors, response schemas, idempotency, and cleanup.

Exit: each feature is below the threshold and its existing API and integration
scenarios pass; frontend clients require no product changes.

### R5. Split the large coordinators

1. Split application configuration/route wiring and Runtime lifecycle/run execution.
   Preserve `create_app`, startup/recovery ordering, and shutdown ownership.
2. Split Channels incrementally: models/access and routes; messages/artifacts;
   delivery/admission; scheduling/reconciliation. Preserve request budgets,
   authorization, durable receipts, event order, and cancellation boundaries.
3. Split CloudComputers incrementally: configuration/admission and routes;
   operation-step handlers; reconciliation/cleanup; provider routing.
   In particular, break up the long `step()` orchestration without reordering
   provider calls or changing unknown-outcome recovery.

Exit: runtime restart/cancellation, channel waits/revocation, cloud response-loss
reconciliation, and supervision tests pass. No changed retry or scheduling policy.

### R6. Refactor deployment tooling and recheck margins

1. Keep `deploy/azure-infra.py` as the compatible CLI facade and extract bounded
   modules within a deployment-domain directory. Preserve direct execution and
   `spec_from_file_location` loading used by `test_azure_infra.py`; verify import
   behavior without relying on an accidental working-directory search path.
2. Preserve generated profiles/environment text, command ordering, exit codes, and
   resource ownership checks. Use recorded Azure responses for validation; this
   refactor does not authorize provisioning real resources.
3. Recount the watch-list files and every new file after Ruff. Split any module that
   reaches 450; verify source/resource paths and packaged artifacts.

Exit: compatible CLI and host packaging, no remaining file at the split threshold.

### R7. Enforce and close

1. Remove all temporary size exceptions and enforce the size and test-location
   checks in normal local and CI gates.
2. Run the complete validation matrix on the final tree. Compare test mappings,
   schemas, public imports, package contents, and CLI behavior with R0.
3. Update affected documentation and the implementation ledger with actual before/
   after sizes, commands, outcomes, environment details, and any unresolved evidence.

Exit: every acceptance criterion below is satisfied. Unavailable required test
environments leave this stage open; collection or mocked checks cannot close it.

## Validation and completion evidence

For each code change, run the project pytest suite using the workspace interpreter
(`python -m pytest`), not only the split module's tests. Run focused regressions
during development. Before completing a batch, apply
`python -m ruff check --fix <changed-python-files>` and
`python -m ruff format <changed-python-files>`, review their edits, recount sizes,
and rerun tests on the final formatted code. Diagnose and fix actual test, syntax,
lint, and typing failures without asking humans to perform engineering work.

Use the [Makefile](../Makefile), [CI workflow](../.github/workflows/check.yml), and
[operations guide](021-foundation-operations.md) for prerequisites. Make defaults
to Windows paths; use `make BIN=.venv/bin <target>` on Linux/macOS.

| Gate | Required evidence |
| --- | --- |
| Baseline and final pytest collection | All existing cases and parameter sets accounted for through old-to-new node mapping; new guard tests included |
| Python regression | Full `python -m pytest`; ordinary `-m "not docker and not windows_desktop"` matrix on Linux/Windows with Python 3.11 and 3.13 |
| Docker and browser integration | Build the current sandbox image with `make sandbox`; `make check-docker` must pass with `--require-docker` and installed Playwright browsers |
| Native desktop | `make windows-test` in the qualified, separate Python 3.11 companion environment; preserve both job and interactive native probes |
| Standalone demo | `make behave` with Docker/Azurite and locked optional dependencies; dry-run discovery alone is insufficient after moving harness code |
| Frontend | Unit tests, ESLint including moved tests, TypeScript/production build, and the full Playwright suite |
| Static and packaging | `make check`, including Ruff, both Pyright configurations, core wheel/import isolation, and wire-schema drift checks; build/import moved packages |
| Architecture and docs | New size/location checks, existing architecture guards, documentation checks, and `git diff --check` |

R0 must record existing environment-specific skips. Platform-specific tests may be
excluded from an inapplicable matrix job only if they pass in their designated
environment. No new skip/xfail or relaxed assertion is an acceptable fix.
Existing warnings must not increase. Report external provider qualifications
separately; mocked Azure tests do not imply a real Azure deployment was exercised.

Completion requires:

- Every repository-owned `.py` file is below 450 active lines after formatting;
  the hard 500-line ceiling is never exceeded by any final artifact.
- No application source directory contains test modules, test fixtures, or test-only
  support. Existing frontend and demo tests are explicitly discovered outside source.
- Every original test case remains accounted for, and all required suites pass on
  the final tree with no concealed failure or unavailable mandatory gate.
- Public imports, API/event schemas, CLI behavior, configuration, data compatibility,
  side-effect ordering, and security/approval guarantees remain unchanged.
- All temporary exceptions are removed. Future regressions fail automated checks.
- Updated documentation records the evidence; unrelated foundation milestones are
  not declared complete by this refactor.

## Review and rollback

Deliver one feature or responsibility split per reviewable batch in the order
R0 -> R1 -> R2 -> R3 -> R4 -> R5 -> R6 -> R7. Each batch must pass its gates before
the next dependent batch. Do not combine broad formatting churn with extraction.

Use source-control commits or patches to isolate each completed batch. If a split
changes behavior, stop that batch and repair or revert only its changes, preserving
unrelated work. No database rollback migration should be required because schemas
and stored formats must not change. Keep old import/CLI facades until compatibility
checks establish they can be removed in a separately approved change.

## Evidence collected while preparing this plan

The working tree was clean when audited. The active-line scan parsed all 185
repository-owned Python files successfully. `python -m pytest --collect-only -q`
collected **436 cases** successfully. This is collection evidence, not a fresh test
pass. No application code, tests, configuration, or agent instructions were changed
while preparing this plan; full execution evidence must be established in R0.
