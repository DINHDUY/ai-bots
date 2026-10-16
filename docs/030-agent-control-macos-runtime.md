# Open-Interface macOS runtime and TaskStar bridge

The [approved plan](029-agent-control-macos-companion-plan.md) is implemented in
source with portable and scripted integration tests. Interactive native and live
model qualification remain open. This guide describes the development runtime;
it does not certify a supported macOS release or a distributed signed binary.

## Installation and local consent

Use the repository's locked workspace (Python 3.11/3.13, uv 0.11.14, Node 24).
The native environment is separately locked to Python 3.12 dependencies and is
installed under `data/oi/venv`; Apple Silicon and macOS 14+ are the initial target.
The host must have an unlocked signed-in console session. Hosted macOS CI runs
portable tests; it cannot establish interactive support.

```sh
uv sync --locked
make BIN=.venv/bin macos-setup
data/oi/venv/bin/agentbot-macos doctor
```

Setup downloads immutable, hash-checked Open-Interface and UFO source slices,
applies the [recorded patches](../packages/agentbot-macOS-companion/patches/README.md),
installs hash-locked native dependencies, and installs the editable companion.
It does not pair, start a service, grant permissions, or issue desktop input.
Keep the checkout in place when running the development installation.

1. Start Agent Control and create a bot with **Open Interface · macOS**. Choose
   an owner-held OpenAI or Azure Foundry multimodal credential.
2. In bot settings, choose **Pair a Mac**. Run
   `data/oi/venv/bin/agentbot-macos pair --backend http://127.0.0.1:8000`
   and enter the one-time code at the hidden prompt. Remote origins require HTTPS.
3. Enable Screen Recording and Accessibility for the actual companion
   interpreter/launcher in **System Settings → Privacy & Security**, then restart
   the companion. Never grant these through a remote automation action.
4. Run `make BIN=.venv/bin macos-companion`. From its local menu select a primary
   display window, enable **Share screen**, then **Allow agent control**. Sharing
   and input start disabled on each connection. A whole-primary-display scope is
   an explicit local choice and can reveal other visible applications.
5. Select the paired Mac in bot settings, save, and choose **Connect Mac**. Use
   **Capture now** to inspect the admitted scope before starting a task.

The CLI provides `doctor`, `status`, `stop`, `pair`, `run`, and `forget`. `status`
and `stop` use an authenticated, same-user Unix socket in the private application
support directory. They cannot execute input or enable sharing. The menu supplies
physical takeover detection and local Stop. The companion runs as the regular
user, with an exclusive process lock; it is not a root service or launch daemon.

## Execution and interfaces

`open_interface` selects the `macos_local` provider. It requires one owner-paired
Mac; missing configuration, a revoked credential, or unavailable local consent
fails admission. There is no Docker/Azure fallback. A database uniqueness rule
allows only one active bot binding per device. Local Mac bots are excluded from
shared workspace computers and access by other workspace members.

The companion initiates authenticated WSS to `/api/macos-agents/connect`. Strict
protocol-1 envelopes expose `health`, `capabilities`, `observe`, `capture`,
`detect_ui`, `planner`, `execute`, `action_status`, `cancel`, and `local_stop`.
This is independent of the existing web/event protocol v2. The native worker uses
length-framed inherited pipes instead of a separately addressable socket, reducing
the local input surface; the Unix socket exposes only status/Stop. Frames are
bounded to 8 MiB and both RPC queues to eight requests. Heartbeats continue while
the native worker is occupied, and missing backend contact disables input.

Observations contain window/process identity, AX records, image bounds, display
ID, pixel scale, and a fresh observation ID. Selected-window images come directly
from ScreenCaptureKit, without activating the application or cropping a desktop
image. OI captures only the explicitly shared primary display. Vision OCR returns
text candidates with confidence and image-relative boxes, never AX identities.
Secure input, detected secure fields, ambiguous AX windows, and incomplete AX
inspection are rejected. OCR does not establish that a control is editable.

Supported proposals are focus window, launch an allowlisted app in display scope,
click, move, scroll, drag, AX text replacement, literal Unicode typing, one key or
modifier chord, and wait. Text is bounded and single-line; Enter is a separate
approved key action. Application launch is limited to TextEdit, Calculator and
Safari. There are no shell, Python, AppleScript, clipboard, arbitrary function,
or batch-execution proposals. Input coordinates are relative to the observed
window. Scrolling is directed to that window rather than the current pointer.

Each mutation passes tool selection, policy/manual approval or Autopilot, durable
execution claim, current binding check, and a signed permit. Permits bind device,
run, action, session, generation, connection epoch, local revision, deadline, and
exact action arguments. The local journal claims the action before dispatch.
Changed targets, scope, console session or physical modifiers reject before input;
interruption after possible input records an unknown result. Duplicate action IDs
return receipts and never issue a second input operation.

The planner uses the pinned OI prompt context and one structured proposal per
observation. Backend-owned inference receives the consented capture and bounded
context; model secrets never enter the companion. A completed desktop task needs
current observed AX-value evidence. Dispatch alone is not success. This initial
verification contract cannot certify arbitrary visual-only goals. Workspace
messaging uses the existing authorized channel tools, including communication-only
runs, without accessing a desktop.

## UFO³ TaskStars

A producer calls the real pinned `TaskStar.execute()` with a `TaskStarBridge`.
Pass an owner-authenticated `httpx.AsyncClient` and the selected Mac bot ID. Use
stable producer/task IDs across retries. The producer's authentication is separate
from the companion pairing credential.

```python
from agentbot_macos.taskstar import TaskStarBridge
from galaxy.constellation.task_star import TaskStar

# owner_client is an authenticated httpx.AsyncClient with the backend base_url.
bridge = TaskStarBridge(owner_client, bot_id, producer="my-galaxy")
star = TaskStar(
    task_id="draft-2026-10-16-001",
    target_device_id=paired_mac_id,
    description="Enter a draft in the selected test editor; leave it unsent.",
    task_data={"text": "Xin chào — café — 日本語"},
    timeout=120,
)
result = await star.execute(bridge)
```

The setup's import-isolated UFO slice is in `data/taskstar/source`; add that path
only to the producer interpreter, as the bridge probe does. The control backend
never imports Galaxy. Whole graph scheduling and AIP registration are out of scope.

`POST /api/bots/{bot_id}/taskstars` accepts producer, task ID, device ID,
description, bounded JSON task data, and timeout (at most 900 seconds). Task linkage
and run admission commit atomically. Same identity/input returns the existing
run/receipt; changed input conflicts. `GET /api/bots/{bot_id}/taskstars/{request_id}`
returns running, completed, failed, cancelled, or outcome_unknown with observed
effect and `retryable: false`. Producer disconnection does not cancel a durable
run. A producer timeout is unknown; query the same receipt, never invent another
ID to retry the physical task. Action and task schemas are generated from their
Python contracts into the frontend and checked for drift.

## Recovery, updates and retention

When an action outcome is unknown, the backend interrupts the run, quarantines the
binding, and shows **Recovery required**. Inspect the actual application locally,
disconnect the bot, then reconnect and explicitly resume or create a reconciled
task. A ready companion does not clear an uncertain result. Killing a worker or
pressing Stop does not undo input already delivered; native timing and held-key
cleanup still need interactive qualification.

Pairing secrets live in the user's Keychain. The backend stores only token hashes.
The private directory `~/Library/Application Support/AgentControl/macOS/` retains
`receipts.sqlite` and `journal.identity`; the Keychain record is bound to that
journal identity. Missing/replaced journals prevent reconnecting. Preserve the
original database and WAL together; never delete receipts to release a device.
Quit the companion before backing up or restoring that directory. Follow the
[foundation operations runbook](021-foundation-operations.md) for backend backup,
restore verification and vault rotation. Do not log or copy pairing secrets into
shell arguments, prompts or `.env` files.

For an update: stop agent work, inspect/reconcile uncertain actions, disconnect,
quit the companion, back up its state, update the checkout, run locked setup and
doctor, then pair again only if the credential was explicitly revoked. Rollback
uses the previous checkout and its source/dependency hashes while preserving the
receipt journal. Schema/source incompatibility must fail closed. There is no
automatic login service, silent source update, or automatic restart of tasks.

Disconnect closes a bot binding, not macOS applications or files. Workspace deletion
blocks active native bindings and unknown effects. It removes Mac bot configuration
and inactive binding rows, while preserving account-level devices, enrollments and
TaskStar identity records to prevent reuse. Historical receipt lookup remains
owner-only; after workspace removal it does not claim the deleted run's outcome.
The [deletion inventory](028-workspace-deletion-audit.md) records table policies.

## Qualification and remaining evidence

```sh
make BIN=.venv/bin check
make BIN=.venv/bin check-docker
make BIN=.venv/bin macos-bridge-test
make BIN=.venv/bin macos-test
```

The native target fails on missing/skipped required cases. It uses only a disposable
owned AppKit editor. The manual `macos-native.yml` workflow requires a dedicated
self-hosted Mac with an interactive session and configured TCC. Portable CI includes
macOS alongside Linux/Windows on Python 3.11/3.13.

Recorded results and exact open acceptance scenarios are in the
[validation ledger](metrics/macos-companion-validation.md). In particular, portable
or scripted results do not establish native capture/input, physical Stop latency,
lock/sleep/session switching, Intel support, multi-display support, or live-model
TextEdit/Calculator/browser behavior. These require an interactive qualified host.
