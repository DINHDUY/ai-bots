# macOS companion implementation evidence

Implementation evidence, 2026-10-16; native acceptance remains open. This record distinguishes source implementation
from the native/live-provider acceptance required by [029](../029-agent-control-macos-companion-plan.md).
No deployment, binary distribution, signing or publication was performed.

## Implemented boundaries

- Separate portable `agentbot-macos-companion` workspace package and native
  Python 3.12 environment; upstream source and dependency hashes; OI patch inventory.
- Authenticated outbound companion connection, selected-window SCK / primary-display
  OI capture, AX / local Vision OCR, allowlisted input, short permits, receipt journal,
  independent heartbeats/worker termination, local consent/menu/Stop, private status IPC.
- Thin controller and real pinned UFO TaskStar bridge; atomic task/run identity,
  same-ID conflict/receipt semantics, bounded inference and current evidence checks.
- Backend provider, owner enrollment/configuration, one active binding, shared action
  dispatcher, Autopilot/manual approval, quarantine/recovery, retained identity tables.
- Mac framework/settings/computer workspace, capture, takeover and recovery UI;
  generated contracts, locked setup commands, macOS CI definitions and runbook.

## Executed evidence

- `make BIN=.venv/bin macos-setup`: hash-checked source installation and isolated
  native dependencies passed on macOS 26.6.2 arm64 / Python 3.12.13.
- `make BIN=.venv/bin macos-bridge-test`: real pinned `TaskStar.execute()` invokes
  `TaskStarBridge`, serializes its task description/data and returns an upstream
  `ExecutionResult` using scripted HTTP. No native UI or live inference is implied.
- Partial native API stub names match installed PyObjC 12.2.2 exports. Static stubs
  describe the optional native boundary; they are not runtime substitutes.
- Portable package/backend tests exercise strict actions, signed identities,
  receipt/crash/no-replay behavior, stale/focus/geometry rejection, producer response
  loss, approval/denial/Autopilot/unknown outcomes, owner isolation and no Docker fallback.
- Local Docker image built. Required Docker pytest execution passed: 13 tests.
- `make BIN=.venv/bin check` passed on Python 3.11.15 / Node 24: **568 pytest
  cases**, 15 intentionally deselected native/Docker cases, Ruff, size gate,
  documentation/schema drift, isolated core-wheel import, frontend lint/build,
  and **88 frontend tests**. Global Pyright: zero errors, 268 visible warnings;
  strict foundation: zero errors/warnings. ESLint: zero errors, 30 warnings.
- `make BIN=.venv/bin check-docker` passed: **13 required Docker tests** and
  **42 Playwright tests**, including Mac settings/capture/recovery at desktop and
  mobile widths. The browser gate used locked npm dependencies and its matching
  Chromium build. The Vite build retains its existing large-chunk warning.
- Python 3.13.12 in an isolated locked workspace: **566 full portable tests passed**
  before the final two Mac tests; the final Mac package rerun passed **29 tests**.
  The changes since that full run are confined to the Mac package and its tests.
- `make BIN=.venv/bin behave`: six scenarios passed; the first errored while an
  image build scanned a concurrently removed Playwright artifact. A subsequent
  targeted rerun of that scenario passed (20 steps). All seven scenarios have
  passing execution evidence; the initial aggregate invocation itself failed.
- Final `git diff --check` and documentation link/capability checks passed.
  Backend isolated import confirms no Quartz, AppKit, PyAutoGUI or Galaxy modules
  are loaded. The final source includes a real subprocess Stop/queued-work test;
  that is process-supervision evidence, not native input/held-key qualification.

The first check runs exposed existing environment/fixture issues, which were
corrected: Linux-only host boot-file access in portable Mac tests, missing browser
fixture page and screenshot identifiers, and the MSW 3 `onUnhandledFrame` option.
The locked workspace and native installs do not rewrite `.env`.

## Unavailable acceptance evidence

At initial qualification, `agentbot-macos doctor` reported Screen Recording=false, Accessibility=false and no
unlocked console session for this process. `make BIN=.venv/bin macos-test` therefore
**fails** its required gate (two native cases skipped). This is not a native pass.
The permission/session prerequisites have been requested; the agent must rerun and
fix the native suite once an interactive session is available.

`make BIN=.venv/bin windows-test` cannot start here: `powershell` is unavailable.
Portable Windows tests run with the workspace suite; actual Windows input requires
a qualified Windows host. No hosted CI run or live-model call is claimed.

Remaining acceptance work, without changing the approved scope:

1. Qualify the owned AppKit fixture end to end: selected/occluded-window capture,
   AX/OCR, Retina transforms, Unicode, click/drag/scroll/focus/chords and allowlisted
   application launch. Verify negative secure/password and ambiguous-window cases.
2. Measure local Stop and worker-hang termination; validate physical takeover,
   modifier release/partial input, lock/sleep/user switching and display changes.
   Current timeouts are implementation bounds, not measured native latency.
3. Run the actual TaskStar → backend → scripted model → OI/native path together,
   including crash/restart/response-loss and permission-revocation races. Separate
   bridge and backend probes do not replace this integrated native evidence.
4. Qualify a chosen owner-configured live model on unsent TextEdit drafts,
   Calculator and navigation in an owned browser profile. The current exact AX
   value postcondition is intentionally narrower than arbitrary visual completion.
5. Run native Windows regression for shared control changes and collect the hosted
   Python 3.11/3.13 OS matrix. Retain results before claiming supported platforms.

M0/M2/M3/M5/M6 native exit criteria remain open. Existing F0–F7 foundation gaps are
independent. All engineering work should continue from the current source and this
record; do not reset receipts, weaken required gates or treat skipped cases as passes.

## Connection rejection follow-up

The local incident had failed connection attempts but no Mac bindings or runs.
`data/oi/venv/bin/agentbot-macos status` reported **Connected** while `doctor`
reported Screen Recording=true, a current unlocked console session, and
Accessibility=false. Missing permission caused connection rejection; the old
lifecycle incorrectly marked its unused session failed and inspection incorrectly
reported offline without a binding.

The fix distinguishes a known rejection before binding/RPC from uncertain
provisioning failures, retains rejected request receipts, reports the selected
device's actual readiness, and refreshes the browser's generation after rejection.
Existing unknown-outcome recovery remains required. The user's existing CLI-lock
and session-detection edits are preserved; the corresponding Quartz constants
were checked against the installed native module and added to its partial stubs.

- Focused backend command: `.venv/bin/python -m pytest
  packages/agent-control-backend/tests/test_macos.py
  packages/agent-control-backend/tests/test_macos_connection.py -q`: **13 passed**.
  Covers offline/permission/sharing/busy rejection, explicit retry, durable replay
  across restart, inspection without a binding, stale connections, and preserved
  recovery after binding and unknown input results. Uses scripted companion transport.
- `make BIN=.venv/bin check`: **576 Python tests passed**, 15 Docker/native cases
  deselected; **88 frontend unit tests passed**. Ruff, size, strict typing, schema,
  documentation, isolated wheel, frontend lint and build passed. After adding the
  three native constant declarations, a separate `.venv/bin/python -m pyright`
  passed with zero errors and the original 268 warnings (the first check had 271).
  Frontend lint retains 30 warnings; build retains the large-chunk warning.
- `docker build -f docker/sandbox/Dockerfile -t agentbot-sandbox .` succeeded.
- Final sequential `make BIN=.venv/bin check-docker`: **13 Docker tests and
  44 Playwright tests passed**, including rejected connections and existing Mac
  recovery. The first invocation passed Docker and 43 browser tests; one browser
  test encountered missing JS/CSS assets while the concurrent `make check`
  rebuilt the frontend. The trace confirmed asset 404s. The sequential rerun
  passed without application changes, weaker assertions, or added retries.
- `make BIN=.venv/bin macos-bridge-test`: passed the pinned TaskStar/scripted HTTP
  probe. It does not establish native desktop or live-model execution.
- `make BIN=.venv/bin macos-test`: required gate **failed**, two native cases
  skipped because Accessibility is unavailable. `make BIN=.venv/bin windows-test`
  could not start because `powershell` is absent on this Mac.

Restart the backend to load the fix. Retire an old unused failed session through
the existing **Review and disconnect** flow, then retry after local permissions
and sharing are enabled. No live database repair, credential changes, journal
deletion, automatic desktop retry, native consent grant, or deployment was performed.

## Accessibility capture limit follow-up

On 2026-10-16 the local companion reported both macOS permissions granted and
whole-primary-display sharing enabled. Read-only diagnostics reproduced **AX
inspection exceeded its bound** in Finder: the old traversal stopped at 300
controls after 0.879 seconds, while a structural scan found 816 unique elements
in 1.415 seconds. Window titles and values were not emitted by that diagnostic.

The fix separates complete secure-field inspection (up to 4,096 unique elements)
from the 300-record output budget. Text controls precede layout containers in the
output. Child arrays are no longer silently truncated, shared/cyclic handles are
deduplicated, and failed required tree reads reject capture. Display inspection
uses one shared three-second deadline and visits each window once; only the
target window needs control metadata. A failed observation clears previous
observation/handle state. The [runbook](../030-agent-control-macos-runtime.md#troubleshooting-capture-inspection)
explains remaining timeout/complexity rejections and how to retry capture.

- Focused portable command: `.venv/bin/python -m pytest
  packages/agentbot-macOS-companion/tests -m 'not macos_desktop' -q`:
  **44 passed**. New cases cover larger trees, secure fields beyond the output
  budget, cycles, missing geometry, failed tree reads, final-element timeouts,
  single-pass display inspection and capture prevention after a failed scan.
- `make BIN=.venv/bin check`: **591 Python tests passed**, 15 Docker/native
  cases deselected at collection; **88 frontend unit tests passed**. Ruff, size,
  typing, schema drift, documentation, isolated wheel, frontend lint and build
  passed. This collection preceded addition of the two large-window native cases.
  Global Pyright retained zero errors / 268 warnings; strict typing had zero
  diagnostics. Frontend lint retained 30 warnings and the existing build chunk warning.
- `make BIN=.venv/bin check-docker`, run after the frontend build finished:
  **13 real Docker tests and 44 Playwright tests passed**.
- Changed Python was Ruff-fixed/formatted and reviewed. Size checking reports
  **372 Python files below 450 active lines**. Final Pyright still reports zero
  errors / 268 warnings; `make BIN=.venv/bin docs-check` and `git diff --check` pass.
- `make BIN=.venv/bin macos-test`, Python 3.12.13/macOS 26.6.2:
  **3 passed, 1 failed**, no native skips. New real native cases successfully
  capture a disposable 350-label window both by selected window and by whole
  primary display, retaining the editor in the bounded control list. The existing
  mouse, focus, drag, scroll, wait and stale-observation case also passes. The
  fixture now waits for its AX window as well as WindowServer publication; its
  large-window labels leave the editor unobscured.
- The native keyboard/Unicode case fails: Command-A appends a literal `a`
  instead of selecting existing text; subsequent Unicode text appends correctly
  but fails the required replacement postcondition. An isolated temporary package
  with `accessibility.py` and `native.py` restored from `HEAD`, selected using
  pytest's `pythonpath` override, reproduces the same failure. No input assertion
  was removed or weakened. Investigating modifier-chord dispatch is remaining work.

The native gate is still **not passing**. These capture/mouse results do not close
keyboard qualification, physical Stop timing, lock/sleep/session transitions,
live-model scenarios, other display layouts, or hosted CI acceptance. Windows
native and standalone demo gates were not rerun for this macOS-only change.
Local services, pairing credentials, receipt journals and consent settings were
preserved; no tasks were retried or deployment performed.

## Stop during run cleanup

On 2026-10-16, Steve's Mac run remained `stopping` while the companion continued
to report ready and serve captures. Durable events showed execution telemetry
followed by **Physical input; agent paused** and repeated `run.stopping` events,
with no `run.finished`. No actions existed for that run, and the companion's
receipt journal contained zero claims. The backend task had entered its final
cleanup before the stop request cancelled that await.

A deterministic test reproduced the stranded state before the fix. Run cleanup
now executes in an owned task that the run awaits through repeated cancellation,
including a later shutdown cancellation. No successful final state is published
before operations settle. Existing execution failures stay failed; unknown native
effects stay interrupted/quarantined, and generic unverified termination retains
its existing quarantine behavior.

- `.venv/bin/python -m pytest
  packages/agent-control-backend/tests/test_runtime_finalization.py
  packages/agent-control-backend/tests/test_runtime.py
  packages/agent-control-backend/tests/test_macos.py -q`: **25 passed**. Nine new
  cases exercise late and repeated cancellation, final-event uniqueness, blocked
  admission during drain, and failure/unknown outcomes across three provider types.
  These are local tests with scripted providers; no real desktop input or model
  requests were used.
- Changed Python passed Ruff autofix/format and diff review. The size checker
  reports **373 Python files below 450 active lines**.
- `make BIN=.venv/bin check`: **600 Python tests and 88 frontend unit tests
  passed**, with 17 Docker/native cases intentionally deselected. Ruff, size,
  both typing projects, documentation, isolated wheel, schema drift, frontend
  lint and production build passed. Existing warnings remain: 268 global Pyright,
  30 frontend lint and the frontend chunk-size warning; strict typing has none.
- Live recovery used the existing authenticated `computer/close` endpoint with
  Steve's exact session identity. It returned 200/closed; a fresh API snapshot
  confirmed `cancelled`, a closed computer binding and zero actions. No SQL repair,
  receipt deletion, re-pairing, task replay or desktop mutation was performed.
- With no active runs or input leases, the old backend was gracefully stopped.
  The standard offline backup command retained **914 database/blob files** in a
  protected application-support backup directory. The backend restarted with its
  original command, environment and working directory; `.env` was unchanged.
  `/ready` returned 200, an authenticated Steve snapshot showed a cancelled run
  and an available generation-11 Mac connection, and SQLite quick-check returned
  `ok` with zero foreign-key violations. The companion reconnected with local
  control off, requiring the user's local opt-in. Operation paths and process IDs
  are retained in the ignored `.validation/steve-stop-operation.json` record.
- `make BIN=.venv/bin windows-test` could not run: `powershell` is absent on this
  Mac. Native keyboard/input qualification remains separate from this backend
  cancellation correction; interactive tests were not rerun against the user's
  active companion.

`make BIN=.venv/bin check-docker` passed **13 real Docker tests and 44 Playwright
tests**, run after the frontend build completed. Final documentation/link and
whitespace checks passed. No new Steve task or live-model request was submitted
as part of recovery.
