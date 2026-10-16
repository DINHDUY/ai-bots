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

`agentbot-macos doctor` reports Screen Recording=false, Accessibility=false and no
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
