# Microsoft UFO Windows companion

Agent Control can pair a signed-in Windows PC, show its selected application in the live workspace, and run Microsoft UFO desktop tasks through the existing approval and Autopilot dispatcher. This is an initial owner pilot. The native executor and deterministic integration tests are verified; live model and target-application qualification remain release gates.

## Start the companion

Requirements: Windows 11 with an unlocked interactive desktop, Git, [uv](https://docs.astral.sh/uv/getting-started/installation/), and the Agent Control backend/frontend. Run as your normal Windows account. The backend may run elsewhere; remote connections require HTTPS/WSS. Loopback HTTP is supported for local development.

From this repository:

```powershell
# Backend dependencies, including the portable companion protocol (no native UFO install).
.venv/Scripts/python.exe -m pip install -e packages/agentbot -e packages/agentbot-windows-companion -e "packages/agent-control-backend[dev]"

# Separate Python 3.11 environment, pinned UFO source and hashed dependencies.
./scripts/windows-companion.ps1 setup
```

Restart the backend and rebuild/reload the frontend after updating. Setup installs 95 locked dependencies in `data/ufo/venv`, then installs the companion itself. It leaves the backend environment separate and does not start desktop automation or pair a PC.

1. Create a bot using **Microsoft UFO · Windows desktop**, an existing OpenAI or Azure Foundry credential, and a multimodal model/deployment supporting Chat Completions with image inputs. Both UFO roles use this model.
2. Open **Bot settings → This Windows PC → Pair a Windows PC**. Pairing is available from any bot's settings and adds the PC to your account; **Use this PC** is available only for Microsoft UFO bots. The one-time code expires after ten minutes and is shown only at issuance. If pairing is disabled with a backend update message, restart the updated backend and click **Retry Windows pairing**.
3. Run the pairing command and paste the code into its hidden prompt:

   ```powershell
   ./scripts/windows-companion.ps1 pair -Backend http://127.0.0.1:8000
   ./scripts/windows-companion.ps1 run
   ```

4. In the companion, select a window, enable **Share screen**, and then **Allow agent control**. Sharing a selected window is the default. **Share whole primary display** enables application selection/launch on that display.
5. Back in Bot settings, select the paired PC and click **Save** to save both the bot details and the PC selection. **Use this PC** remains available to apply only the PC selection. Click **Connect Windows PC**, or send the first task to connect it. Every proposed input action goes through the existing approval UI. Autopilot uses that same dispatcher.

`make windows-setup`, `make windows-companion`, and `make windows-test` wrap the corresponding commands. The script accepts `-Backend` for remote pairing; subsequent runs use the paired endpoint stored in the protected profile.

## Paired, but the bot cannot see Windows

Pairing registers a PC with your account; it does not change a bot's framework or assign the PC to a bot. A bot using `microsoft` still uses its Docker sandbox, even if it is named "Windows". Create a new bot with **Framework → Microsoft UFO · Windows desktop** (`ufo`). You can reuse an existing PC pairing and model credential.

Use **Create Windows bot** in an existing bot's Windows settings to open **New bot** with Microsoft UFO already selected. Selecting a PC on a non-UFO bot and clicking **Save** now shows an error instead of silently ignoring the selection. For UFO bots, **Save** applies a pending PC selection before closing the popup. If assignment fails, the popup stays open with the reason; the error also indicates when the bot details have already been saved.

In that UFO bot's **Bot settings → This Windows PC**, select the online PC and click **Use this PC**. In the companion, select an open application window (or explicitly select the whole primary display) and enable **Share screen**. Close Bot settings, click **Connect Windows PC** in the **Local Windows PC** panel, and use **Capture now** to verify the shared screen. Viewing only requires sharing; running tasks also requires **Allow agent control** locally. If the bot is paused, explicitly **Resume agent** after restoring local control.

A selected-window share exposes only that application. Enable **Share whole primary display** locally if the task requires discovering or launching other applications. If multiple pairings have the same PC name, select the online entry; starting the companion does not reconnect older pairing profiles.

## Local control and recovery

- **Share screen** permits inspection, captures, and transmission to Agent Control/the configured model. Turning it off discards pending observations and prevents new ones.
- **Allow agent control** permits approved UI input. Autopilot cannot enable this local permission.
- **Hand off**, below **Allow agent control** in the companion, lets the agent continue when you physically move/click the mouse or use the keyboard. It starts unchecked on every companion launch and takes effect immediately. It does not enable sharing/control, resume a paused bot, or change approvals/Autopilot. Uncheck it to restore automatic pause on physical input.
- **STOP / Ctrl+Alt+F12**, locking Windows, an unavailable input desktop, and connection loss fence automation even with **Hand off** checked. Physical keyboard/mouse input during a task also pauses automation when **Hand off** is unchecked. Only the companion's own workers are terminated.
- Mouse takeover requires movement, a button transition, or scrolling. Empty device notifications and repeated stationary absolute-position reports are ignored. With **Hand off** unchecked, actual movement still pauses the bot, including while Autopilot is enabled.
- **Take control on this PC** pauses the bot and asks the companion to stop. Use your physical keyboard/mouse. This release does not forward remote browser input to Windows.
- To continue, restore local sharing/control and select **Resume agent** in Agent Control. A reconnect alone never resumes input. To use the approval UI on the same PC during automation, check **Hand off** before starting/resuming the task. Otherwise, use another device for approvals or explicitly resume after local changes.
- **Disconnect Windows PC** retires this bot's binding and stops its companion workers. It leaves Windows, applications, documents, and PC files intact. Idle expiry also disconnects the binding. Hibernate, reset, deletion of a VM, and workspace cleanup are unavailable for this provider.

If an input might have executed but its result is lost, its durable action result is `unknown`, and the computer is quarantined. Inspect the application yourself, disconnect the bot, reconnect and enable local control, then issue a new task describing the actual state. The previous action ID is never automatically replayed. A companion receipt claimed without a final result also remains unknown after a crash.

Failures before any native input now return **Action not executed** with the actual reason, rather than requiring recovery. This includes expired permits, changed windows/focus, and controls without writable UI Automation text support. Observations identify writable text controls so UFO can distinguish a message editor from read-only page content. Stale-target and expired-permit rejections allow at most two new observations and fresh action proposals; each proposal goes through approval/Autopilot again. Rejected action IDs retain their result and are never replayed. If execution started before an error, the original reason is retained and recovery still applies; the run ends as interrupted instead of remaining stuck on Stopping.

After updating this behavior, restart both the control backend and the Windows companion. Existing unknown outcomes still need inspection and disconnection. **Hand off** suppresses physical-input pauses, but switching foreground windows can still invalidate an action's target; the bot must observe and propose again.

### Teams message editor: literal typing

The Teams CKEditor message box can advertise a writable UIA value while `set_edit_text` fails with **Literal text input failed; no keystroke fallback**. Observations now identify this editor with `text_input_method: type_text`. UFO proposes a separate `windows.type_text` action, approved through the same approval/Autopilot flow. Other writable editors continue to use `set_edit_text`.

Activating Teams does not necessarily focus its message box. Observations include `has_keyboard_focus`. If the editor lacks focus, UFO must propose a separate approved `click_input` on the editor, observe again, then propose `type_text`. A typing request without editor focus is rejected before execution with `editor_not_focused`; local control stays enabled and the bot may make a fresh proposal within its two-retry limit. During typing, UFO verifies the existing focus instead of calling the editor's UIA `SetFocus` again, preserving the caret established by the click.

`type_text` inserts up to 2,000 characters at the current caret/selection using literal Unicode input. It neither clears the draft nor interprets shortcut syntax, and rejects line breaks and control characters. It checks the focused editor, window identity, local session and permit before each small input batch, and refuses typing while modifier keys are held. The agent must inspect the following observation to verify the draft. Pressing Enter or clicking Send requires a separate action and an explicit user request to send.

If UFO proposes `set_edit_text` for this rich-text editor, the companion rejects it before executing and allows a fresh observation and proposal with its own approval (at most two retries). It never switches input methods after an uncertain write. Partial input or a focus/session/deadline failure after execution starts still requires inspection and recovery.

Running on the same PC does not make injected keystrokes or simulated mouse movement count as physical takeover. **Hand off** also suppresses actual physical-input pauses. However, **Allow agent control** is turned off after an uncertain action failure, independently of the input hooks. A status such as **Typing target changed** indicates a target guard failure; newer errors identify whether the editor lost focus, the foreground window changed, or the window identity/title/geometry changed. Check the companion's reason to distinguish this from **Physical mouse/keyboard input; agent paused**.

To load this change, restart `agentbot-control` and the Windows companion; setup and pairing do not need to be repeated. If the bot already shows **Recovery required**, inspect the Teams draft, disconnect the bot, then select **Connect Windows PC** and restore local control. Try a new task such as **Type Hello in the Teams message box; do not send it**, describing any existing draft text. A native test-owned editor verifies the typing path; writing into a live Teams conversation has not been tested.

**Connected / Local control enabled** in the companion (formerly **Connected · Ready**) reports its current connection and local permissions. It does not confirm the outcome of a previous bot action. A bot can still show **Recovery required** after an interrupted action or backend restart. Inspect the application, use **Review and disconnect → Disconnect PC** in the bot's recovery notice (or **× / Disconnect Windows PC** in the Local Windows PC header), then select **Connect Windows PC** and enable local control. Send a new task describing the current state. Restarting the companion, enabling Autopilot, or checking Hand off does not clear this recovery requirement.

If you see **Worker request cancelled before dispatch** from an older companion, check the companion's status for **Physical mouse input** or **Physical keyboard input**. Local takeover also applies while the planner is starting unless **Hand off** is checked. Restore **Allow agent control**, then click **Resume agent** and leave the PC's mouse and keyboard idle, or enable **Hand off** before resuming. The updated companion includes the stop reason in interrupted worker responses and sends the local pause state before the error, so the backend records a local pause promptly. Restart the companion to load these updates and the **Hand off** checkbox; the existing pairing is retained.

Only one bot may hold a connected binding to a PC at a time, even when idle. A Windows session mutex also prevents running a second companion under another pairing profile on that desktop. Disconnect the first bot before selecting/connecting a second writer. This is deliberately stricter than allowing several idle bindings to share one execution lease.

UFO bots, their desktop captures, and their history are owner-only. Workspace membership, execution grants, groups, and routines do not grant someone else access to that desktop. Selected-share creation is disabled for these bots.

### COM error after sending a Teams message

`COMError: (-2147220991, 'An event was unable to invoke any of the subscribers', ...)` is HRESULT `0x80040201`. In Windows UI Automation, this is [`UIA_E_ELEMENTNOTAVAILABLE`](https://github.com/microsoft/win32metadata/blob/main/generation/WinSDK/RecompiledIdlHeaders/um/UIAutomationCoreApi.h): an element reference is no longer available. Teams can replace UI elements after sending or updating a conversation; the generic COM message does not describe a Teams delivery error.

The companion retries only `observe` and `capture` for this exact HRESULT, with at most three attempts and short waits. It discards stale observations, reacquires the UIA root and keeps the selected HWND/process identity pinned. Window-only sharing binds directly to that window instead of inspecting other applications. Each attempt rechecks the interactive session; local Stop and sharing changes still fence the worker. Other errors are not automatically retried.

These retries never repeat a click, keystroke, or text write, and the planner retains the previous action's result. If inspection still fails, the task stops with an inspection-specific error; previous action receipts remain intact. An error during an input action still follows the existing unknown-outcome rules. If the message is already visible in Teams, do not repeat the send request because of an inspection error. Restart the Windows companion to load this update, restore sharing/control, and ask it to inspect the chat without sending again.

### Combined keyboard shortcuts and invalid proposals

`keyboard_input` accepts one key or shortcut per action. For example, `^a{DELETE}` combines **Ctrl+A** and **Delete**, so it is rejected before either key is executed. UFO must propose `^a`, inspect the result, then propose `{DELETE}` separately if clearing is needed. To replace text, it can select with `^a` and propose `type_text` in a later step. Every valid step uses a fresh observation and passes through approval/Autopilot; denying a step stops the sequence.

Schema errors, unsupported functions and action batches now return correction feedback to the planner without ending its worker or losing completed-action history. The backend allows at most two corrected proposals per run, then stops after a third invalid proposal. Rejected proposals never reach approval or execution, and combined shortcuts are never expanded into hidden actions. Validation feedback omits raw input values and the Pydantic traceback. Restart both `agentbot-control` and the companion to load this update. If earlier typing completed before the rejection, describe the current draft in the next task.

## Implementation boundary

`windows.py` adds owner pairing, revocation, outbound authenticated WebSockets, provider routing, and a Windows binding behind the existing sandbox manager interface. Migration `013_windows_computers.sql` adds paired computers, one-time enrollments, bot compute configuration and unique active bindings. Existing run/action/approval/event tables remain authoritative.

The companion starts separate planner and desktop subprocesses over private stdio pipes. Windows Job Objects terminate these owned workers when the companion exits; launched applications break away from the worker job so Stop does not close user documents. The planner instantiates the pinned UFO `HostAgent` and `AppAgent`, uses their prompt constructors and response schemas, and exchanges one proposal/result per step with the backend adapter. Agent Control supplies a small Host/App transition loop; the upstream standalone CLI, processor execution loop, Galaxy, retrieval and MCP server lifecycle are not run.

Model requests return to `UfoAgentAdapter` in the backend. It selects only the admitted bot's credential/model/endpoint, bounds messages and inline PNG images, limits output and time, and disables hidden SDK retries. Credentials are never sent to the companion. Each run logs source revision, profile version and configured model. Native UFO/UIA modules are never imported by the backend.

Each mutation follows proposal → approval/Autopilot → immutable claim → signed permit → local validation → durable receipt claim → UFO executor → observed result. Permits expire after eight seconds and bind action ID, session/generation, connection epoch, local permission revision and immutable arguments. The companion checks the permit again after waiting for its worker; the native worker checks deadline and interactive-session availability immediately before input. A pre-dispatch check does not undo input already delivered to an application.

The executor uses UFO's `ControlInspectorFacade`, window/desktop photographers, `ActionExecutor`, and `AppPuppeteer`. It retains observation-scoped UIA references, process creation identity, window title/bounds/DPI, current foreground and control properties. Cached UFO inspection wrappers are refreshed before use. Observations expire after 30 seconds; approvals based on older observations fail and require a new proposal. Captures carry title, time, sequence, dimensions, physical bounds, DPI and viewport revision.

| Canonical action | Actual path | Result semantics |
| --- | --- | --- |
| `windows.select_application_window` | Observed UIA window `set_focus`; no maximize or outline | Focus is checked independently. |
| `windows.launch_app` | Fixed System32 `notepad.exe` / `calc.exe`, desktop scope only | Launch dispatched; subsequent observation must confirm. |
| `windows.set_edit_text` | UFO `ActionExecutor` → `SetEditTextCommand` → UIA value write | Literal text, up to 16,000 characters; current value verified. No Enter or typing fallback. |
| `windows.type_text` | UFO `ActionExecutor` → companion `TypeTextCommand` → Unicode `SendInput` | Up to 2,000 literal single-line characters at the caret/selection of an observed writable editor. No shortcuts or Enter; following observation must verify the draft. |
| `windows.click_input` | UFO `ClickInputCommand` | Button/double-click allowlist; dispatch result and following observation. |
| `windows.keyboard_input` | UFO `keyboardInputCommand` | One bounded navigation key/shortcut; no repeats, held keys, or typing fallback. |
| `windows.wheel_mouse_input` | UFO `WheelMouseInputCommand` | At most ten wheel units per action. |
| `windows.click_on_coordinates` | UFO `ClickOnCoordinatesCommand` | Finite normalized window coordinates with current geometry/focus checks. |

Dispatch success and verified effect are separate. `effect_observed` is retained with action results. Model completion text says that UFO reports completion; it is not an independent assertion that all task effects were verified.

File browsing/upload into the Windows filesystem, browser automation, terminal/shell, Office COM, arbitrary executable arguments, dynamic MCP registration, save/close helpers, arbitrary Puppeteer commands, drag and batch execution are not exposed. The WU8 extensions remain deferred. Screen/Activity views and existing chat/approval/Autopilot controls remain available.

## Source, dependencies and patches

Pinned Microsoft UFO: `a795552d976c4c019d7c2f778a0effb5cef7de6b`. The source stays in ignored `data/ufo/upstream`; the implementation is versioned in `packages/agentbot-windows-companion`. `requirements-ufo.in` records the explicitly selected dependencies; `requirements-ufo.lock` includes hashes and transitive pins. The backend imports only the lightweight protocol package.

`bootstrap.py` applies exact, versioned replacements and compares complete expected files at every worker start. Unexpected tracked/staged changes and untracked source files are rejected. Compatibility patches cover:

| Upstream file | Patch purpose |
| --- | --- |
| `ufo/automator/__init__.py` | Remove API/shell/Office receiver registration. |
| `ufo/agents/agent/basic.py` | Disable eager retrieval imports and retriever creation; no RAG stack in this subset. |
| `ufo/automator/ui_control/screenshot.py` | Use window-only PrintWindow capture; reject failure instead of capturing the desktop. |
| `ufo/automator/ui_control/controller.py` | Verify the actual UIA value, prohibit text/keyboard fallbacks, and propagate click/scroll errors. |

Pywinauto/UIA can block, and processes run with the user's account privileges. Worker separation provides independent supervision, not a Windows security sandbox. The allowed schema is the only entry point exposed to model output; the trusted pinned dependency itself is not sandboxed against the user account.

Pairing stores only token hashes in the backend. The local bearer credential is protected with Windows DPAPI in `%LOCALAPPDATA%/AgentControl/companion.bin`; the at-most-once receipt journal is beside it. Protect this directory and keep the journal through upgrades. Deleting receipts while retaining a live credential invalidates replay protection. Raw worker stdout/stderr is not retained as a second transcript; retained captures and backend events use existing storage/authentication rules.

## Verification and pilot limits

Verified on 2026-10-08 with Windows 11 build 26200, Python 3.11.12 for UFO, and Python 3.13.13 for backend tests:

- Hashed dependency setup, source qualification, and real HostAgent/AppAgent prompt/response construction.
- An owned Win32 test window: scoped capture without focus changes, focus verification, literal Unicode text containing key-like syntax, a real button click, stale geometry rejection, independent input hooks, desktop mutex exclusivity, and real companion worker IPC/receipt replay. Synthetic UFO mouse input does not trigger the physical-input watcher in this check.
- The literal-typing probe: real UFO Host/App proposal construction and execution of `type_text` into a test-owned Win32 editor, including an emoji and literal `{ENTER}`/`^s` text, verified through UIA without activating the button. Portable tests cover modifier keys, focus changes between batches, partial input without replay, schema validation, and backend approval/permit handling.
- UIA read recovery: the native fixture injects `0x80040201` during inspection, reacquires the window root and verifies unchanged text/focus. Portable tests cover bounded retry, partial-observation invalidation, selected-process identity, session loss, worker read routing, and a post-click read failure without replaying the click, including when recovery is exhausted.
- Proposal correction: real UFO schemas reject `^a{DELETE}`, retain prior results and accept separate `^a`/`{DELETE}` proposals. Portable tests verify worker continuity, bounded correction, fresh observations, separate approval steps and stopping on denial.
- Deterministic backend tests: pairing secrecy/one-time use/ownership, no Docker fallback, manual approval and denial, Autopilot, one binding per PC, unknown outcomes and no replay, and disconnect without touching the PC.
- Portable protocol tests: tampering, expired/old-epoch/old-revision permits, malformed actions, crash-persistent receipts, queued-work fencing, dead connections, and termination of a deliberately hung owned worker within a two-second test bound.
- Native process supervision: closing the worker Job Object terminates its owned process while preserving a launched application surrogate. Mouse movement takeover uses raw hardware input so programmatic cursor moves are not mistaken for operator input.
- Frontend unit/build/browser tests, including local readiness, pairing, desktop/mobile layout and accurate disconnect wording.

Initial rollout checks: 164 Python tests passed, including all nine Docker tests; 36 frontend unit tests and 23 browser tests passed; the production frontend build and explicit native probe passed. No live model call was made.

Latest Windows checks: 260 portable Python tests passed (nine Docker tests excluded), including injected-input filtering, rejection without disabling control, UIA read recovery without replay, and bounded proposal correction. The native `--text-only` probe passed with a separate editor click, observed focus, literal typing and recovery from an injected stale-element COM error. The `--planner-only` probe passed against the installed UFO schemas with correction feedback and separate Ctrl+A/Delete proposals. No text was entered into a live Teams conversation.

Run portable checks and the **explicit interactive** probe:

```powershell
.venv/Scripts/python.exe -m pytest -m "not docker and not windows_desktop"
npm test --prefix packages/agent-control-frontend
npm run test:e2e --prefix packages/agent-control-frontend
./scripts/windows-companion.ps1 test
```

The interactive probe opens and closes only its own test window. It does not pair a device or call a live model. Ordinary pytest discovery excludes the downloaded UFO tree.

To verify only literal typing without reserving the companion's desktop mutex or STOP hotkey:

```powershell
data/ufo/venv/Scripts/python.exe packages/agentbot-windows-companion/tests/native_probe.py --text-only
```

This also briefly focuses a test-owned editor; run it while no bot is controlling the desktop.

To check the installed UFO parser and proposal correction using synthetic observations, without desktop input or a model call:

```powershell
data/ufo/venv/Scripts/python.exe packages/agentbot-windows-companion/tests/native_probe.py --planner-only
```

Remaining release qualification: a real configured multimodal deployment, Notepad save, Calculator, Explorer, the selected target application, repeated-task success/latency measurements, lock/UAC/RDP transitions during real input, and mixed-DPI/monitor changes. This build is not qualified for unattended use, elevated apps or secure desktops. Whole-display sharing is limited to the primary display; off-display windows are excluded. The synthetic test does not establish compatibility with every application's UIA/PrintWindow implementation.

## Revoke, update and rollback

Revoke pairing from Bot settings to fence its bots and reject future connections. Then close the companion and run `./scripts/windows-companion.ps1 forget` to remove the protected local credential. Forget does not silently erase the receipt journal or retained backend history.

Before updating, Stop locally and disconnect the bot. Keep the credential/journal and database together with their current history; rerun setup and the native probe. Changing the UFO source pin or patch inventory requires protocol, bypass and native qualification again. If qualification fails, leave control off and restore the previous application build. Do not restore an older SQLite database over active runs or delete Windows documents as part of rollback. Docker bots continue through the original provider.
