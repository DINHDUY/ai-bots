# Python size refactoring validation

Updated 2026-10-09. Implements the approved [R0-R7 plan](../022-python-size-refactoring-plan.md)
against `839b6bbfd72608a7011176a9e45668ba9f25e07e`. The working tree initially contained
only the untracked plan. Local configuration and `.git/AGENTS*` files were preserved.

Implementation is finished. Final native desktop qualification is pending an unlocked
Windows desktop; the native probe passed after its extraction in R1. This is local
validation evidence, not a hosted CI run or a live Azure qualification.

## Size and layout

| Measurement | Before | After |
| --- | ---: | ---: |
| Maintained Python files | 185 | 272 |
| Files exceeding 500 active lines | 18 | 0 |
| Files with 450-500 active lines | 3 | 0 |
| Largest file, active lines | 1,860 | 432 |
| Frontend unit tests under production `src` | 15 | 0 |

The [machine-readable inventory](python-size-refactoring.json) records active and
physical counts for every baseline/current Python file, the current Python content
hash, and all 27 changed test node IDs. The checker counts executable multiline
strings but excludes blanks, comments, and AST-identified docstrings. It scans tracked
and non-ignored new files. The enforced threshold is 450, without exceptions.

Backend feature modules now use flat domain packages with explicit compatible exports.
Catalog, EventStore, Runtime, Channels, CloudComputers, and the other public coordinators
retain their state and thin typed forwarding methods. Extracted operations share the
original database, locks, queues, tasks, and callbacks. Docker and Anthropic adapters,
Windows routing, and the Azure CLI have equivalent bounded modules.

Python test helpers remain under package `tests/`. Frontend tests and their three
support files moved to `packages/agent-control-frontend/tests/`; TypeScript, ESLint,
and Vitest include them. The Behave feature, environment, steps, and split harness
are under `docs/usecases/tests/behavior/`. Demo behavior remains outside the product.
The root `AGENTS.md` is 34 lines and explicitly forbids tests in production source.

## Compatibility evidence

- All 436 baseline pytest cases, including parameter combinations, remain collected
  and passed. There are 23 additions: 22 size/location regression cases and one
  regression for source digests across extracted adapter files. An AST audit also
  preserves all 298 original test functions' decorators and assertion counts.
- OpenAPI matches the baseline structure exactly. Replay schema output and Azure CLI
  `--help` match the baseline bytes. Existing route, approval, receipt, recovery,
  cancellation, storage, and provider tests continue to pass.
- SQL call totals per extracted domain are unchanged. The architecture guard now
  records exact extracted paths and non-growing SQL call budgets; it does not exempt
  whole new packages. The existing ceiling of 160 async transaction blocks remains.
- All five distributions build as wheels. Their installed modules import from the
  wheel installation, migrations are included, tests are absent, and old module files
  do not coexist with their replacement packages. The core wheel independently
  imports without backend, Docker, Anthropic, Microsoft, or product-tool extras.
- `deploy/azure-infra.py` retains direct CLI and file-based import compatibility.
  The native probe also supports direct execution and file-based import without
  an accidentally preconfigured test path; its synthetic planner probe passes.
- Tool manifest hashing includes every Python member of a split adapter package,
  so changes to extracted implementations still invalidate pinned code revisions.
  No database migrations, persisted formats, configuration defaults, dependencies,
  or user-facing feature changes were introduced.

## Executed checks

| Check | Result |
| --- | --- |
| Baseline full Python suite | 436 passed, including 10 Docker cases |
| Final full Python suite, Windows 3.11.12 | 459 passed, no skips or xfails |
| Ordinary Python suite, Windows 3.11.12 and 3.13.13 | 449 passed and 10 Docker cases deselected on each |
| Ordinary Python suite, local Linux containers 3.11.14 and 3.13.11 | 449 passed and 10 Docker cases deselected on each |
| `make sandbox` | Passed; current sandbox image built |
| Required Docker suite | 10 passed with `--require-docker`, 449 other cases deselected |
| Frontend unit, ESLint, TypeScript/build | 72 passed across all 15 files; zero lint errors |
| Playwright | All 34 browser tests passed |
| `make behave` | 1 feature, 4 rules, 7 scenarios, 100 steps passed; no skips |
| `make check` | Passed: Ruff, size/location gate, both Pyright projects, ordinary pytest, docs, isolated core wheel, wire drift, frontend lint/build/tests |
| Native job and interactive probes | R1 passed; final job probe passed, interactive retry awaits unlocked desktop |
| Native import and `--planner-only` | Passed with the separate companion interpreter |

Global Pyright remains at zero errors and 251 warnings, matching this refactor's
baseline; strict foundation checking has zero errors/warnings. Frontend ESLint
retains its 30 baseline warnings. The existing frontend bundle-size warning remains.
The workspace uses uv 0.11.14, Node 24.18.0, and npm 11.16.0.

## Reproduction and environment notes

Run the plan's Make targets from the repository root. On this Windows machine,
putting `C:\Program Files\cygwin64\bin` first on the child process's `PATH` avoids
mixing Cygwin's npm script path with another Bash installation. For frontend fixture
checks, set `VITE_API_BASE=http://127.0.0.1:8000` in that child process; the user's
ignored local configuration points at port 8001 and was left unchanged.

Linux matrix runs use fresh source snapshots and locked installs in local Debian
containers. Select the container interpreter explicitly with
`uv sync --locked --python "$(command -v python)"`, then invoke the resulting virtual
environment directly. The root `.python-version` otherwise selects 3.11 in a 3.13
container. No credentials, local `.env` files, or TLS bypasses are used.

The first full Behave run exposed a pre-existing stale expectation:
`bash error: command timed out after 30s.`. The existing production response is
`bash error: command timed out.`. Only the demo assertion was corrected. It now also
asserts the 30-second limit's elapsed bound and zero upload requests, retaining the
no-partial-blob assertion. Production timeout behavior was unchanged.

Native qualification operates only on its own test window. Later retries encountered
`Windows refused focus`; investigation identified `LockApp.exe` covering the desktop.
No assertions were relaxed and no lock-screen input or credentials were supplied.
An unlocked interactive session is necessary to finish that required gate.

Temporary logs, JUnit XML, source snapshots, package artifacts, and baseline schema
captures are retained locally under ignored `.validation/refactor/`. Hosted CI,
real Azure provisioning, and live cloud-model qualification were not performed.
The unrelated F0-F7 repository/worker migration and recovery work remains open.
