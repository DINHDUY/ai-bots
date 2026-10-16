# Agent Control implementation tracking

## Foundation remediation: current working tree

Updated 2026-10-09 against baseline `ac164dc`. Implementation of [F0-F7](020-foundation-remediation-plan.md) has started, but the full plan is **not complete**. No release or production deployment is claimed. [ADR-0017](adr/0017-foundation-boundaries-and-recovery.md) records the implemented choices; [operations](021-foundation-operations.md) describes installation, limits, keys and recovery.

| Milestone | Implemented | Remaining acceptance work |
| --- | --- | --- |
| F0 | Compatible uv workspace lock, Python 3.11/3.13 and Node 24 setup, CI definition, required Docker execution, isolated core-wheel probe, schema/link checks, reproducible architecture measurements | Hosted Linux/Windows evidence and branch protection need a remote; qualify the six-minute reference workload and native companion environment |
| F1 | Dependency-free core installation, explicit integration extras, separate maintained product package, injected tool factories and source-aware manifest digests, import guard | Finish generic connector/skill schema and dispatch conventions still present in SDK adapters; qualify optional integration distributions |
| F2 | All 21 service fields typed; zero subsystem constructors taking runtime; explicit composition/callbacks; dispatch/streamer extraction; stable scheduler error classification; six strict modules | Complete public collaborator typing and strict coverage, centralized state transitions, removal of remaining dynamic routing/compatibility constructor; reduce 256 visible global warnings |
| F3 | Bounded authentication work and durable throttling; versioned keyring/legacy readers; offline resumable rotation of six sealed columns; atomic deployment/per-owner admission quotas | Maintained workload egress enforcement, resource-policy revisions and unattended eligibility, real DNS/redirect/bypass tests, Chromium sandbox review, live Azure/native desktop evidence, fully populated provider rotation drill |
| F4 | Bounded cancellation-aware worker API, explicit read transactions, replay repository/read offloading, action persistence offloading, post-commit notifications | Exclusive worker connection ownership, removal of CatalogConnection and indirect blocking helpers, migration of business SQL and remaining 160 async transaction blocks, load/ownership acceptance |
| F5 | Side-effect-free event/snapshot schema generation, runtime frame validation, generated TypeScript envelopes, workspace panels and shared-view route separated, bounded cloud/channel backend packages, Fast Refresh rule enforced | Complete domain event and HTTP request/response schemas, remaining query/invalidation consolidation |
| F6 | Commit-driven v2 replay with catch-up, send bounds and five-second reconciliation/permission checks; SPA v2 only; no page-local automatic approvals; preserved explicit retry IDs | Full race/slow-consumer/load evidence and measured read/delivery behavior; inventory legacy external consumers before endpoint removal |
| F7 | Required worker progress/readiness and admission rejection; optional cloud degradation; database/worker diagnostics; offline database/blob backups and fenced verification restores; upgrade/key runbook | Aggregate metric export/alerts, correlated bridge logs, complete receipt/job/journal retention, populated isolated provider recovery drill with measured RTO/RPO, release assessment/version/changelog |

Local combined regression: **426 Python tests passed on each of Python 3.11 and 3.13**, with 10 Docker tests intentionally deselected from each ordinary run. Frontend: **72 unit tests and 34 Playwright tests passed**, with successful build. Global Pyright: zero errors and 256 warnings; strict foundation configuration: zero errors/warnings. Frontend lint: zero errors and 30 existing warnings; Fast Refresh warnings: zero. The separate Docker and clean-install evidence is recorded in the [validation record](metrics/foundation-validation.md).

The [committed baseline](metrics/foundation-baseline.json) and [working-tree measurements](metrics/foundation-current.json) identify their source and backend content hash. Runtime constructor dependencies fell from 10 to zero, and `Any` service fields from 20 to zero. The async transaction count remains 160; it is not evidence of a completed database migration. `WorkspaceCenter.tsx` now owns the settings shell, with members, groups, routines, toolkit, notifications, search, profile and shared viewing in separate modules.

Next implementation priorities are F3a containment/resource policy, F4 complete worker/repository ownership, then full F5 contracts and F7 capacity/recovery qualification. Existing invariants and current tests remain required throughout; the open items above cannot be closed by unrelated regression results.

### Follow-up: remove the ETL demo from the application

ETL instruction presets, automatic legacy instruction migration, the built-in tool registration and the installed ETL handler have been removed. The standalone sample and its tests are under `docs/usecases`. General bot instructions/default prompts and tool extension contracts remain available. Saved demo bindings become unavailable and can be removed without silently rewriting user instructions.

Follow-up validation: 426 Python tests, 72 frontend unit tests and 34 browser tests passed. The product wheel and frontend bundle contain no ETL implementation or preset strings. Ruff, type checking, lockfile and documentation checks passed; existing warning baselines remain.

### Follow-up: Python size and test separation

The approved [R0-R7 refactor](022-python-size-refactoring-plan.md) is implemented.
All 272 maintained Python files are below 450 active lines (maximum 432), compared
with 21 files at or above that threshold before extraction. Size and test-location
checks now run in `make check` and CI without exceptions. Public module paths remain
compatible through explicit domain package exports; tests and their support stay
outside production source.

Validation covers all 436 original pytest cases plus 23 new checks, the local
Linux/Windows Python 3.11/3.13 matrix, 72 frontend unit tests, 34 browser tests, and
7 Behave scenarios. The final native job probe passed; interactive qualification
passed in R1 but its final retry needs the Windows desktop unlocked. Exact sizes,
test moves, compatibility checks, and current gate status are in the
[validation record](metrics/python-size-refactoring.md).

This completes the structural cloud/channel decomposition, while the broader F5
contract work remains open. SQL and transaction boundaries are unchanged; the
160 async transaction blocks and outstanding F0-F7 acceptance work are not closed
by this refactor.

### Follow-up: shared workspace computer

A workspace owner can switch eligible bots onto one workspace-owned computer.
The default remains one live computer per bot. [ADR-0018](adr/0018-optional-shared-workspace-computer.md)
and [023](023-shared-workspace-computer.md) record the mode, the Windows/UFO
exclusion, and the shared-desktop limitation. Snapshots add `scope`,
`workspace_id`, and `attached_bot_ids` as extra fields; the typed wire contract
was not changed.

Local evidence on 2026-10-12, Python 3.11, Windows:

- `ruff check` passed. `scripts/check_python_size.py`: 281 Python files below 450 active lines.
- Pyright: 0 errors, 256 warnings. Strict foundation project: 0 errors, 0 warnings.
- `pytest -m "not docker and not windows_desktop"`: 455 passed, 11 deselected.
- `scripts/docs_check.py`, `scripts/verify_core.py`, and `scripts/check_wire.py` passed.
- Frontend ESLint: 0 errors, 30 existing warnings. Production build succeeded. Vitest: 74 passed. Playwright: 35 passed, including the shared computer settings tab.
- `make windows-test`: companion job probe and native probe passed.
- `pytest -m docker`: 11 passed, including the two-bot shared container test, against the local `agentbot-sandbox` image.

`make check` reaches the frontend `npm` steps and then fails in this Git Bash
because `npm` is not on that shell's path. Those frontend commands passed when
run from PowerShell. Live Azure execution of the shared computer is not covered;
the shared cloud test uses the mocked driver. The async transaction count remains 160.

### Follow-up: Markdown workflow import

The approved [I1-I4 plan](024-markdown-workflow-import-plan.md) is implemented.
[Workspace settings → Import workflow](025-markdown-workflow-import.md) accepts
agent Markdown files, previews the exact bodies without YAML frontmatter, and
creates one bot per file in a new shared-Docker workspace. All imported bots have
messaging bindings, published purposes, enabled participation, and automatic
collaboration. Credentials, model choices, and tools are reviewed before commit.
No computer or model run starts during import.

One database-worker transaction saves the workspace, bots, configuration, channel
events, and durable owner-scoped receipt. Tests cover rollback after bot/enrollment/
receipt writes, concurrent retries, cancellation, restart, stale previews, foreign
credentials, deletion, exact Unicode/LF/CRLF preservation, and identical sources.
The importer keeps receipts after bot deletion. Idle shared-mode bot removal now
avoids per-bot computer retirement and rejects removal while a computer or task is
active. Generated HTTP schemas/types have a drift gate. Frontend test configuration
pins its fixture API origin independently of local development settings.

Validation on 2026-10-12, Windows, Python 3.11.12:

| Command / gate | Result |
| --- | --- |
| `uv lock`; `uv sync --locked --inexact --no-install-package agent-control-backend` | Locked dependencies resolved/checked; PyYAML 6.0.3 is now a direct backend dependency. |
| `ruff check --fix` and `ruff format` on changed Python files | Passed; automated edits reviewed and followed by full regression. |
| `.venv/Scripts/python -m pytest --require-docker -q` | **514 passed**, no skips. Includes the standalone demo's Python tests. |
| `make SHELL=powershell.exe ".SHELLFLAGS=-NoProfile -Command" check` | Passed: **502 Python tests**, 12 Docker cases deliberately deselected; lint, typing, docs, isolated core-wheel install, contract drift, frontend build and **80 unit tests**. |
| `make SHELL=powershell.exe ".SHELLFLAGS=-NoProfile -Command" check-docker` | **12 real-Docker tests** and **37 browser tests** passed. Import browser cases cover 1600 px and 390 px, edits, response loss and reload recovery. |
| `make windows-test` | Companion job probe and native desktop/IPC/receipt probe passed. |
| `make docs-check`; `git diff --check`; explicit new-file whitespace check | Passed. |

All 296 maintained Python files are below 450 active lines. Global Pyright remains
at zero errors / 256 existing warnings; the strict foundation project has zero
errors or warnings. Frontend lint remains at zero errors / 30 existing warnings.
The production build retains its existing large-chunk warning. An initial full
frontend run failed because a local API origin used port 8001 while fixtures used
8000; the test-only configuration fix was followed by a successful complete gate.

Normal `uv sync --locked` could not replace the executable held by the running
control service. The successful command above checked dependencies without
reinstalling that backend launcher. The existing service and `.env` were preserved;
this work does not claim a live deployment. Startup of the updated backend applies
migration `020_workflow_imports.sql`.

Messaging acceptance uses the real Microsoft/Anthropic adapters with mocked model
responses, including mixed-framework request/reply/continuation. The new Docker
case proves imported bots share one session and file, retain approvals, and both
pause for human control. Live model calls, live Azure, fresh hosted Linux/Windows
matrix execution, and the standalone Behave scenarios were not run for this change.
Existing foundation F0-F7 acceptance gaps remain open.

### Follow-up: 16,000-character bot instructions

The requested limit increase applies to bot creation/editing, workflow import
validation, advertised import capabilities, UI guidance, and specifications.
Tests accept 16,000 characters and reject 16,001, preserve imported Unicode and
CRLF/whitespace, and verify that rejected writes leave saved resources intact.
Both model adapters pass the full body to mocked provider requests. History bounds
and Anthropic's output-token budget remain independent of the instruction limit.

Validation on 2026-10-12, Windows, Python 3.11.12:

- Changed Python files passed `ruff check --fix` and `ruff format`; formatting
  changes were reviewed. The focused boundary/adapter suite passed all 35 tests.
- `make SHELL=powershell.exe ".SHELLFLAGS=-NoProfile -Command" check` passed:
  509 Python tests, 12 Docker tests deliberately deselected, 80 frontend unit tests,
  frontend build, lint, typing, documentation, core-wheel, and contract drift gates.
- `make SHELL=powershell.exe ".SHELLFLAGS=-NoProfile -Command" check-docker`
  passed all 12 real-Docker tests and 37 browser tests. Together the two gates
  exercised all 521 Python tests. Final `make docs-check` and whitespace checks passed.
- All 298 Python files are below 450 active lines. Existing warning baselines
  remain: 256 global Pyright warnings, 30 frontend lint warnings, and the frontend
  large-chunk build warning. Strict foundation typing has zero errors or warnings.

No dependency, migration, or native-companion implementation change was needed.
The running backend was preserved; its next restart loads the new limit. Native
desktop probes, standalone Behave scenarios, live model calls, and hosted CI were
not rerun for this limit change.

### Follow-up: workspace deletion

The approved [D1-D4 plan](026-workspace-deletion-plan.md) is implemented and locally
qualified in the working tree. [Workspace settings → Delete workspace](027-workspace-deletion.md)
supports empty and populated custom/imported workspaces. Personal is protected;
only the owner can preview and confirm. Runs, claimed automation, transfers,
leases, nonclosed computers, and uncertain outcomes block deletion. Confirmation
binds an exact name and current impact digest to a durable request ID.

Migration `021_workspace_deletions.sql` adds workspace/bot tombstones, deletion
receipts, cleanup items and transfer markers. Catalog removal and preference
repair commit together on the database worker. SQL triggers and parent foreign
keys fence stale producers. The [exhaustive audit](028-workspace-deletion-audit.md)
is checked against migrated tables; populated-content and rollback tests verify
dependency order and foreign-key integrity. New SQL stays in repository modules.

Cleanup validates individual storage identities, runs outside catalog transactions,
survives cancellation/restart, preserves pending bytes, and exposes retryable disk
failures in owner history. Closed per-bot/shared computer dependencies are removed;
account credentials and external computers remain. Inactive Azure inventory is
owner-recoverable through workspace, historical bot, or profile association;
profile reload keeps deleted workspaces disabled. Deletion never calls provider
resource deletion. Historical imports remain receipts and cannot recreate content.

Frontend confirmation, blocker links, pending/failed cleanup, original-request
recovery, and retained inventory live in their own feature directory. Workspace
and channel selections reject stale URLs, reconcile other tabs, and fall back to
Personal. Deleted bots lose sessions and caches; old bot routes recheck access.
Deletion contracts join the side-effect-free schema generation and drift gate.

Local qualification on 2026-10-12, Windows/Python 3.11/Node 24:

- `make check` with PowerShell shell flags passed: 529 Python tests, architecture
  rules, core-wheel isolation, schema drift, documentation, frontend build and
  85 frontend unit tests. Two subsequently added socket/share and staging cleanup
  tests passed separately; final cloud/profile/recovery/architecture checks passed
  17 tests after the inventory association fix.
- Changed Python passed Ruff autofix/format and review. Size checks report 321
  Python files below 450 active lines. Global Pyright: zero errors, 254 baseline
  warnings; strict foundation: zero errors/warnings. Final frontend lint/build/unit
  rerun passed with 30 existing lint warnings and the existing chunk-size warning.
- Final `make check-docker` passed 13 real Docker tests and all 40 browser tests.
  Docker covers deletion after shared computer closure while preserving an
  unrelated live computer. Browser checks cover exact confirmation, response loss,
  reload recovery, desktop/mobile, another tab, stale channel URLs and cleanup retry.
- `make windows-test` passed native job supervision, scoped capture/input,
  literal Unicode, stale-target rejection and companion receipt replay.
- `make behave` passed 7 scenarios / 100 steps using real Docker and local Azurite
  with scripted model responses. `make docs-check` and whitespace checks passed.

Azure inventory tests use a fake provider; no live Azure resource deletion or model
call is claimed. Hosted CI was not run. Initial qualification preserved the running
backend and `.env`; the subsequent local repair below applied migration 022 and
restarted that backend. Foundation F0-F7 gaps above remain separate work.

### Workspace deletion: deployed schema repair

On 2026-10-12 a local database had recorded an early version of migration 021,
before `workspace_deleted_operations` and the file-writer staging/state columns
were added. Deletion rolled back with `no such table: workspace_deleted_operations`;
the cleanup worker also could not query its missing columns. Re-running startup
could not repair an already recorded migration. The browser hid the plain-text
HTTP 500 behind its generic unknown-result message.

Forward migration 022 creates the missing table and conditionally adds columns in
one transaction, preserving databases already on the final 021 schema. Regression
tests cover both schemas, transfer-marker preservation, actual deletion afterward,
idempotent restart and rollback of an interrupted migration. The HTTP client now
preserves non-JSON error statuses; the deletion UI reports HTTP failures while
retaining original request IDs for uncertain outcomes.

Live local recovery: all five custom workspaces deleted successfully in a repaired
in-memory database copy; the live catalog was not deleted. After verifying zero
active runs, computers, transfers, claimed jobs and control leases, the affected
backend was stopped, a protected 1,721-file database/blob backup was created under
the current user's local application-data directory, and the backend restarted on
port 8001. Migration 022 is recorded, both writer columns exist, and `/ready` returns
200. Six active workspaces and zero deletion receipts remained after repair.
The existing browser request can be retried with its original ID. `.env` and other
services were preserved. Operation paths are recorded locally in
`.validation/deletion-repair-operation.json`.

Focused validation passed seven migration/race tests and six deletion UI tests.
Final `make check` passed 534 Python tests, 87 frontend tests, build, lint, generated
contracts, architecture/core isolation and docs checks. `make check-docker` passed
13 real Docker tests and all 40 browser tests. Changed Python passed Ruff
autofix/format; 323 Python files remain below 450 active lines. Pyright remains at
zero errors / 254 baseline warnings, strict foundation at zero diagnostics, and
frontend lint at 30 baseline warnings. Live SQLite quick-check returned `ok`, with
zero foreign-key violations; both environment-file hashes were unchanged. Native
companion and standalone Behave checks were not repeated for this schema/client
repair; their earlier qualification above still applies.

### Workspace deletion: collapsed settings panel

The Delete workspace panel now follows all other Workspace settings content and
uses a native disclosure that starts collapsed, including after reload. Expanding
it exposes the existing confirmation, request recovery, and deletion history.
The user guide, approved plan, and frontend requirement reflect this layout.

Validation on 2026-10-12: `make check` passed 534 Python tests and 87 frontend unit
tests, plus build, lint, typing, contract, core-isolation and documentation gates.
`npm run test:e2e --prefix packages/agent-control-frontend` passed all 40 browser
tests; existing desktop/mobile deletion tests now verify bottom placement,
default collapse, expansion, and recovery after reload. Existing warning baselines
remain. Docker, native companion, and standalone Behave checks were not rerun for
this UI-only follow-up.

## macOS companion: implementation and qualification

The user approved implementation of the [Open-Interface/macOS plan](029-agent-control-macos-companion-plan.md)
on 2026-10-16. The new package supplies the native runtime, portable TaskStar
bridge/controller, hash-pinned OI/UFO source adaptations, and isolated native
setup. Backend `open_interface`/`macos_local` integration, owner pairing, durable
task/action receipts, approvals, single-device bindings, recovery, and frontend
Mac settings/workspace are implemented. [030](030-agent-control-macos-runtime.md)
documents setup, limits, task submission and retained state.

Portable and scripted results are separate from native qualification in the
[validation record](metrics/macos-companion-validation.md). `make check` passed
568 Python and 88 frontend tests; `make check-docker` passed 13 Docker and
42 browser tests. A separate Python 3.13 run and the real pinned TaskStar bridge
probe also passed with the coverage limits recorded there. The local required
native gate fails because Screen Recording, Accessibility, and an unlocked console
session are unavailable to this process. Native operation/Stop measurements,
lock/session transitions, live-model scenarios, and native Windows regression
remain open. This is not completion of all M0–M6 exit criteria or a supported
native release. CI definitions are present but hosted runs are not claimed.

## Prior feature baseline

B1 and B2 remain the execution foundation. B3–B11 are implemented across the backend, sandbox image, and frontend with the initial release scope below. See [runtime contracts and deployment instructions](016-agent-control-backend-runtime.md) and the [frontend guide](009-agent-control-frontend.md).

- [x] B3: inspected health, capture provenance/history, observed capture and frontend status
- [x] B4: confined binary files, revisions, artifacts, uploads and attachments
- [x] B5: exclusive human leases, input fences and explicit resume boundary
- [x] B6: real PTYs, bounded replay and lease-bound cleanup
- [x] B7: reset, hibernate, resume and bounded keep-warm
- [x] B8: workspaces, roles, selected sharing, notifications and authorized search
- [x] B9: group conversations and bounded explicit handoffs
- [x] B10: private-input recording, versioned skills and a scoped reference connector
- [x] B11: durable routines/triggers and onboarding
- [x] AP1–AP4: persisted owner-controlled Autopilot, pending/future decisions, dispatch fencing, synchronized UI and decision history
- [x] 012–019: tool libraries, workspace channels, capture retention, cloud computers, and the related frontend (see the numbered docs)
- [x] Review items 1–4 (foundation): composition root, one database connection, repositories for the hot tables, local `make check` gates. Tagged baseline is `v0.3.0`

## Open items

- The compatible uv workspace lock is now supplied with this change; installation and tests ran on Python 3.11 and 3.13. Hosted platform evidence remains pending.
- Repository migration remains open in the `cloud/`, `channels/`, `routines/`, `groups/`, `toolkit/`, `workspaces/`, `windows/`, `runtime/`, `event_store/`, `app/`, `approvals/`, `capture_retention/`, `store/`, and `control/` domain packages, as well as the remaining legacy modules. `tests/test_architecture.py` uses exact extracted paths and non-growing SQL budgets alongside the legacy allowlist. The promoted helpers (`events.append`, `receipts.save`/`find`, `approvals.resolve`, `runs.active`) and computer health writes already live in `repositories/`.
- Pyright on the backend and Windows companion is `basic`, with these diagnostics downgraded to warnings: `reportAttributeAccessIssue`, `reportArgumentType`, `reportMissingImports`, `reportOptionalMemberAccess`, `reportCallIssue`, `reportOptionalSubscript`, `reportIndexIssue`, `reportGeneralTypeIssues`, `reportOperatorIssue`, `reportOptionalIterable`, `reportOptionalOperand`. The prior per-execution-environment `typeCheckingMode` setting was unsupported by Pyright. The new supported strict project covers six migrated foundation modules; remaining packages use the visible basic warning baseline.
- Package `version` fields are still `0.1.0`. The git tag `v0.3.0` is the reviewed baseline; bumping the package versions is a separate change.

## Implementation map

| Milestone | Main implementation |
| --- | --- |
| B3 | `agentbot_control/computer.py`, typed capture metadata in `agentbot/interfaces.py`, Docker inspection, native probes/supervision, LiveScreen/SessionContext. |
| B4 | `files.py`, `blob_store.py`, native no-follow file helper and inotify/rescan watcher, LiveFiles and composer Attachments. |
| B5 | `control.py`, shared action locks, native browser/desktop input, `session/humanControl.ts`, ComputerControls. |
| B6 | `terminals.py`, native terminal daemon/client, lazy xterm InteractiveTerminal. |
| B7 | `lifecycle.py`, Docker stop/start/removal, persisted operation journal and retention, deadline-aware runtime sweeper. |
| B8 | `workspaces.py`, current membership authorization, execution/share grants, preferences, notifications, FTS and WorkspaceCenter. |
| B9 | `groups.py`, durable messages/handoffs, bounded delegation and ordinary runtime admission, group UI. |
| B10 | `toolkit.py`, reviewed immutable skills, private recording, GitHub manifest/runner and tools in both real adapters. |
| B11 | `routines.py`, immutable definitions and jobs, time/webhook/event dispatch, recovery, routine editor/history and onboarding. |
| Autopilot | `autopilot.py`, migration 012, approval/dispatch and routine integration, `AutopilotToggle`, monotonic session state and durable attribution. |

Migrations 003–011 persist these resources in the existing catalog. The sandbox keeps B2 protocol 2 and adds computer protocol 3. Rebuild the image and recreate old computers after retaining needed files. `CONTROL_WORKSPACE_FEATURES` permits a staged rollout; service and permission checks also govern each computer's capabilities.

## Historical feature verification

Validation on 2026-10-07: 132 Python tests without Docker and nine real-Docker tests passed; 33 frontend unit tests and 17 Playwright browser tests passed. The production frontend build, Python lint checks, and Git whitespace checks passed. Autopilot uses migration 012 and requires no change to the previously rebuilt `agentbot-sandbox` image.

The suites use deterministic model fixtures; the Docker suite executes real local containers. GitHub connect/health/invoke/rotation/revocation tests use controlled HTTP responses, including expired credentials and network failures. No live GitHub repository, cloud model, or Azure Storage publication was exercised.

| Suite | Evidence |
| --- | --- |
| Existing Python regression | Catalog/auth, raw gateway, durable runtime, both adapters, approval policies, event replay and process cancellation. |
| `test_autopilot.py` | Existing-schema upgrade, owner/member/grant boundaries, duplicate/stale writes, pending/future decisions in both adapters, before/after-dispatch races, disable/re-enable fencing, expiry/denial/Stop, context drift, human pause, lifecycle/restart persistence, interrupted recovery, routines and handoffs. Real Docker verifies unattended file creation followed by a manual gate after disabling. |
| `test_workspace_services.py` | Inspect-only access, capture ownership, competing/fenced control, private input and disconnect, lifecycle idempotence, roles/grants, selected shares, preferences, groups, DST and signed delivery deduplication. |
| `test_automation.py` | Parameterized skill replay and drift, both adapter connector dispatch paths, scoped GitHub invocation/revocation, routine admission restart recovery, event-loop prevention and notifications. |
| `test_service_limits.py` | Missed schedules, bounded queues, disabled features, chunked request limits, copied SQLite/blob restoration with encrypted credentials, group admission recovery, connection outage, failed input-service retirement and failed reset recovery. |
| `test_computer_services_docker.py` | Real browser/Xvfb captures and input, independent browser failure, complete binary transfer, protected/symlink/special-file rejection, subprocess invalidations, hibernate/resume, PTY resize/Unicode/replay overflow/interrupt/background cleanup. |
| `test_live_api_docker.py` | Authenticated multipart upload/retry, complete revision-bound download, overwrite/protection errors, human lease, real terminal input/output/list/close and cleanup. |
| Frontend | Unit/protocol regression, production build, and Playwright workspace/approval/reconnect/responsive flows plus fenced human input, partial-preview/full-download behavior and routine editor/history. Autopilot checks cover acknowledged state, lost-response retry, inline errors, read-only/capability behavior, stale revisions, durable attribution, cross-tab settings changes and compact/mobile layout. |

Run from the repository root:

```powershell
docker build -f docker/sandbox/Dockerfile -t agentbot-sandbox .
.\.venv\Scripts\python -m pytest -q
npm run test --prefix packages/agent-control-frontend
npm run build --prefix packages/agent-control-frontend
npm run test:e2e --prefix packages/agent-control-frontend
```

## Initial release boundaries

- The connector catalog contains scoped GitHub repository issues over a fine-grained PAT. OAuth providers, arbitrary MCP endpoints, public executable packages and billing are not listed or implemented.
- Teaching stores reviewed structured steps and explicit parameters; coordinate steps stop on drift. Terminal activity becomes a manual checkpoint rather than a recorded transcript.
- Groups require explicit mentions and selected context. Group routines use manual/time/webhook triggers and each target bot's approval mode. Autopilot permits unattended decisions for opted-in bots; group event triggers and group policy selection remain unavailable.
- File search indexes eligible retained filenames. Protected files are metadata-only through general file APIs; there is no general secret-management upload flow.
- Screenshot observation is bounded; there is no video stream. Hibernate preserves files, not process memory. The runtime remains one process per SQLite deployment.
- Live-provider and Azure Blob ETL cloud validation still require a configured external integration environment; local completion does not establish cloud publication.
