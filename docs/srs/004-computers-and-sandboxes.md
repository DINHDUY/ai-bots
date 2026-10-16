# SRS-004 Computers and sandboxes

Docker sandbox, Windows companion, Azure computers, and the services that observe or operate a live computer. `INV-003`, `INV-004`, `DEC-002`, `DEC-003`, `DEC-004`, `DEC-012`, and `DEC-018` apply.

## Docker manager and hardening

| ID | Requirement |
| --- | --- |
| CMP-001 | `get_or_create` MUST return the cached sandbox, else reattach a container labeled `agentbot.session_id=<id>` (starting it if stopped), else `containers.run` named `agentbot-<id>`. |
| CMP-002 | `close` MUST force-remove the container and destroy `/workspace`. SDK calls MUST run in `asyncio.to_thread`. Every exec MUST have a host-side timeout. |
| CMP-003 | The manager MUST implement `configure_scope`, `bind`, `legacy_candidate`, `inspect`, `existing`, `reconcile`, and `hibernate`. |
| CMP-004 | The container user MUST be non-root `agent` uid 1000 with `HOME=/home/agent` and `WORKDIR=/workspace`. Capabilities MUST be dropped (`ALL`). `security_opt` MUST include `no-new-privileges:true`. Limits MUST be `mem_limit=2g`, `nano_cpus=1e9`, `pids_limit=512`, `shm_size=1g`, and a 256 MiB `nosuid` tmpfs on `/tmp`. Mounts MUST be none. Network MAY be default bridge. Seccomp and AppArmor MAY stay at Docker defaults. |
| CMP-005 | Sandbox protocol label `2` MUST gate execution. Computer protocol label `3` MUST gate computer services. Both MUST be verified before container creation. Image pull MUST be host preparation, not a side effect of a chat request. |
| CMP-006 | The entrypoint MUST start Xvfb `:99` at 1024×768×24, openbox, and `browserd.py` on `/tmp/agentbot-browser.sock`, then wait for the socket. |
| CMP-007 | `run_bash` MUST wrap the command in `timeout --signal=KILL 30s bash -lc`, demux stdout and stderr, prefix a non-zero exit with `exit N`, report timeout as `bash error: command timed out after 30s.`, and cap output at 16000 characters. |
| CMP-008 | File writes MUST use `put_archive` (uid/gid 1000, mode 0644) after `mkdir -p`. Reads MUST use `get_archive`. Every path MUST pass `resolve_workspace_path`, which normalizes backslashes, `.`, and `..`, and rejects anything outside `/workspace`. |
| CMP-009 | File-service opens SHOULD be descriptor-relative and no-follow. Lexical checks alone are not sufficient for the live file API. Symlinks and special files MUST be rejected. |
| CMP-010 | `desktop_plan.plan_action` MUST accept exactly these 17 names: `screenshot`, `zoom`, `left_click`, `right_click`, `middle_click`, `double_click`, `triple_click`, `left_click_drag`, `mouse_move`, `left_mouse_down`, `left_mouse_up`, `cursor_position`, `scroll`, `type`, `key`, `hold_key`, `wait`. It MUST reject unknown names. Coordinates MUST lie in 1024×768. Scroll MUST be at most 50. Key repeat MUST be at most 100. `type` MUST be at most 10000 characters. Durations MUST be at most 30 seconds. Key names MUST use a modifier whitelist and MUST NOT contain control characters. |
| CMP-011 | `screenshot`, `zoom`, `cursor_position`, and `wait` MUST NOT require approval. Every other desktop action MUST. `desktop.py` MUST execute the plan and return JSON with an optional base64 PNG. |
| CMP-012 | `browserd.py` MUST own one persistent Playwright page and serve one JSON request per Unix-socket connection. `browserctl.py` MUST be the one-shot client. Every browser action MUST return a PNG. Chromium MAY use `--no-sandbox` only because the container is the boundary. |
| CMP-013 | Helpers MUST communicate by process exit and JSON on stdout. They MUST NOT listen on network ports. |
| CMP-014 | An alternate backend MAY implement `ISandboxClient` plus `get_or_create` and `close`. It MUST keep per-session labels, reattach after restart, server-side path confinement, command timeouts, output caps, and PNG screenshots. |

## Health, files, control, terminals, lifecycle

`CONTROL_WORKSPACE_FEATURES=0` MUST advertise B3–B11 capabilities as disabled and MUST stop new scheduled dispatch. B1/B2 readers, run recovery, and cleanup MUST stay active. `CONTROL_WORKSPACE_FEATURES=1` enables those routes.

| ID | Requirement |
| --- | --- |
| CMP-015 | `GET /api/bots/{bot_id}/computer` MUST be inspect-only and MUST NOT create or start a container. Health polls SHOULD run every `HEALTH_POLL_SECONDS` (10). Observations MUST be stale after 30 seconds. Inspection MUST time out at 6 seconds. Viewers and probes MUST NOT extend idle lifetime. Missing evidence MUST be `unknown`. A failed service in a running container MUST be `degraded`. |
| CMP-016 | Captures MUST be PNG, at most 4 MiB, at most 4096 pixels per side, and at most 16 megapixels. On-demand interval MUST be at least 0.5 seconds. Metadata MUST include surface (`browser` or `desktop`), epoch, sequence, viewport revision, dimensions, sanitized URL or title, and cursor only when fresh. |
| CMP-017 | File listings MUST page at 200 entries. Previews MUST be at most 64 KiB. Uploads and downloads MUST be at most 64 MiB. Downloads MUST require the expected revision. Paths MUST stay under `/workspace`. |
| CMP-018 | Protected names (`.env`, `*.pem`, `*.key`, and credential files) MUST expose metadata only. They MUST NOT be uploaded, previewed, downloaded, shared, or text-indexed. Artifact content MUST be immutable with `Content-Disposition: attachment` and `nosniff`. A run MUST retain at most 20 output versions. Artifact expiry MUST default to 7 days. |
| CMP-019 | Uploads MUST be multipart with request id, path, expected revision (`missing` for new), and bytes. A run MUST accept at most 10 attachment ids and MUST verify owner, instance, and current revision. Successful retries MUST preserve the upload id. Selecting the Files tab MUST NOT create a sandbox. |
| CMP-020 | The workspace watcher MUST coalesce inotify with a periodic rescan, bounded to 10000 entries and 1000 watches. Overflow MUST relist. Events are invalidations, not a complete write audit. |
| CMP-021 | A human lease MUST last 30 seconds and the UI MUST renew it about every 10 seconds. Fields MUST include login, tab client id, surface, generation, expiry, and a monotonic fencing token. Two tabs of one user MUST still compete. The agent MUST be stopped and drained before takeover and MUST stay paused after release or lease loss. Resume MUST be an explicit fresh turn. Lease loss MUST release held buttons and keys and MUST NOT silently resume the agent. |
| CMP-022 | Control input MUST include generation, lease fence, surface, capture or viewport revision, and sequence. Stale, duplicate, out-of-bounds, or historical-image input MUST be rejected. |
| CMP-023 | PTY sessions MUST be real bash PTYs. Limits MUST be one PTY per lease and two per workspace, a 256 KiB replay buffer, 4 KiB input chunks, 32 KiB/s WebSocket input, at most 200 rows and 400 columns, 5 minutes idle, and 1 hour absolute. Disconnect MUST close the PTY and its process group. Clipboard escape sequences MUST be disabled. Terminal ids MUST NOT be run or action ids. |
| CMP-024 | Lifecycle commands `create`, `close`, `reset`, `hibernate`, `resume`, and `keep-warm` MUST require request id and expected generation. The journal MUST record completion only after reconciliation. Interrupted lifecycle operations MUST NOT be repeated automatically. |
| CMP-025 | Close MUST destroy the instance and workspace and MUST keep the bot and transcript. Reset MUST retire the old instance and MUST NOT present old files as a fresh workspace. Hibernate MUST stop the container, retain `/workspace` for 7 days, and MUST NOT preserve process memory, the browser page, or `/tmp`. Resume MUST reprobe services, change the surface epoch, and leave the agent paused. |
| CMP-026 | Keep-warm MUST be at most 120 minutes and at most two computers per owner. Idle close MUST default to 15 minutes with a 1-minute warning. Health probes MUST NOT refresh that deadline. |
| CMP-027 | Command supervision MUST bound each output stream to 16000 bytes, enforce deadlines after output descriptors close, and on cancellation MUST signal the shell process group. Unverified termination MUST block another writer and MUST expose recovery or close. |
| CMP-028 | Teaching private mode MUST suppress recorded input and captures while enabled. |

## Shared workspace computer

| ID | Requirement |
| --- | --- |
| CMP-029 | Modes MUST be `per_bot` (default) and `shared`. Only the workspace owner MAY change mode, and the request MUST send the current revision. A change MUST fail with `computers_active` while any eligible computer or the shared computer is not closed. |
| CMP-030 | Shared mode MUST attach eligible bots to one `computer_sessions` row with `bot_id` null and `workspace_id` set. Eligible providers MUST be the Docker sandbox and Azure. UFO and paired Windows PCs MUST keep per-bot computers. |
| CMP-031 | Bot-level create, reset, hibernate, close, and cloud lifecycle MUST fail with `workspace_computer` in shared mode. Workspace lifecycle MUST fail with `computer_busy` while a run or human lease is bound. A run that references a shared session that is not running MUST fail with `workspace_computer`. |
| CMP-032 | Overlapping runs MAY share focus, tabs, files, and processes. Actions MUST still serialize on the session lock. A human lease MUST pause every attached bot. The shared computer MUST count once toward capacity and MUST be charged to the workspace owner. Status changes MUST be written in the same transaction to every attached bot's event stream. |
| CMP-033 | Snapshots MUST report `computer.scope = "workspace"`, `workspace_id`, and `attached_bot_ids` as extra fields. The typed wire contract MUST NOT be broken to add them. Per-bot cloud configuration MUST be locked while shared mode is on. The shared computer MUST use a workspace compute profile. |

## Windows companion

The companion requires an unlocked interactive Windows desktop. Its venv MUST be Python 3.11, separate from the backend. Setup MUST install the locked UFO dependency set and MUST pin upstream UFO to commit `a795552d976c4c019d7c2f778a0effb5cef7de6b`. `bootstrap.py` MUST compare expected files at every worker start and MUST reject unexpected source changes.

| ID | Requirement |
| --- | --- |
| CMP-034 | A pairing code MUST expire after 10 minutes and MUST be shown only at issuance. The backend MUST store token hashes only. The local bearer credential MUST be protected with DPAPI. A Windows session mutex MUST prevent a second companion on the same desktop. Pairing MUST register a PC and MUST NOT assign it to a bot. Only one bot MAY hold a connected binding, even when idle. |
| CMP-035 | Permits MUST expire after 8 seconds and MUST bind action id, session generation, connection epoch, local permission revision, and immutable arguments. The companion MUST check the permit again after waiting for the worker, and the worker MUST check the deadline and interactive session immediately before input. Observations older than 30 seconds MUST NOT authorize input. |
| CMP-036 | Allowed actions MUST be limited to `windows.set_edit_text` (at most 16000 characters, current value verified, no Enter fallback), `windows.type_text` (at most 2000 literal single-line characters, no shortcuts or Enter), `windows.wheel_mouse_input` (at most 10 wheel units), `windows.keyboard_input` (one navigation key or shortcut, no repeats or held keys), `windows.click_on_coordinates` (normalized coordinates with geometry and focus checks), and `windows.launch_app` (only System32 `notepad.exe` and `calc.exe`, desktop scope). |
| CMP-037 | Combined shortcuts, shell strings, arbitrary executables, file upload into Windows, browser automation, Office COM, drag, and batch execution MUST NOT be exposed. `set_edit_text` on an unsupported rich editor MUST be rejected before execution. Typing without editor focus MUST fail with `editor_not_focused` before execution. `select_application_window` MUST NOT maximize or draw an outline. |
| CMP-038 | UIA HRESULT `0x80040201` MAY be retried at most 3 times, and only for observe and capture. Click, key, and text write MUST NOT be retried. At most 2 corrected proposals per run MUST be allowed; a third invalid proposal MUST stop the run. Rejected action ids MUST keep their result and MUST NOT be replayed. |
| CMP-039 | If input might have executed but the result was lost, the action MUST be `unknown` and the computer MUST be quarantined. Failures before any native input MUST report that the action was not executed. Autopilot MUST NOT enable local Allow-agent-control and MUST NOT resume a paused bot. |
| CMP-040 | Hand-off MUST start unchecked on every launch. Physical keyboard or mouse input MUST pause automation when hand-off is unchecked. Stop, Ctrl+Alt+F12, Windows lock, a missing input desktop, and connection loss MUST fence automation even when hand-off is checked. A reconnect alone MUST NOT resume input. Disconnect MUST leave Windows applications and files intact and MUST terminate only companion-owned workers. |
| CMP-041 | UFO bots, their captures, and their history MUST be owner-only. Membership, execution grants, groups, routines, and selected shares MUST NOT grant desktop access. The backend MUST NOT send credentials to the companion. Model output MUST NOT become arbitrary Python, shell, or dynamic method invocation. |

## Azure computers

Providers MUST be `docker` (default), `windows_local`, `macos_local`, `azure_ml_compute_instance`, and `azure_vm`. Azure computers MUST run the same Linux sandbox image. `CONTROL_COMPUTE_PROFILES` MUST be an absolute path. A bad profile MUST fail startup. Cloud selection MUST NOT fall back to Docker.

| ID | Requirement |
| --- | --- |
| CMP-042 | Azure credentials MUST stay on the backend. The service identity MUST be a managed identity, or `azure_cli` for local development. An ML profile MUST map the Entra object id to the Agent Control owner. Other compute types MUST be rejected for `create_on_behalf_of`. |
| CMP-043 | The reference host MUST be Ubuntu 24.04 with systemd and Docker using iptables. Workloads MUST join `agentbot-workloads`, run as uid 1000, drop capabilities, set `no-new-privileges`, bound CPU, memory, and PIDs, publish no ports, and mount neither the Docker socket nor credentials. IPv6 inside the workload MUST be disabled. The firewall MUST reject host listeners, IMDS `169.254.169.254`, link-local, WireServer, and private ranges. Missing isolation rules MUST refuse sandbox creation. |
| CMP-044 | Enrollment grants MUST last 30 minutes, be hashed and single-use, and bind resource and host fingerprint. The machine credential MUST expire in 7 days; the backend MUST store only its hash. Enrollment codes MUST NOT pass through shell arguments, chat, logs, or workspace scripts. |
| CMP-045 | Managed create MUST require stop support, bootstrap and package URLs with SHA-256, backend URL, Key Vault URL, and host identity ids. A VM MUST use a private subnet, an SSH public key, an immutable image version, `storage_policy=managed_data_disk`, and a dedicated LUN-0 disk. Create MUST NOT create or delete a public IP, resource group, VNet, or ML workspace. |
| CMP-046 | The backend MUST reserve resource name, binding, generation, and receipt in one transaction before calling Azure. After restart or a lost acceptance response it MUST poll the original resource and MUST NOT automatically reissue an ambiguous mutation. |
| CMP-047 | `idle_policy=manual` MUST leave power to the operator. `idle_policy=stop` MUST track an explicit stop and MUST NOT delete resources. Reset sandbox MUST retire only the recorded container. Detach MUST revoke host access and MUST leave machine data. Managed deletion MUST be an explicit administrator action. Attached resources MUST NOT be deletable. Reattach MUST wait until cleanup is resolved. Guest shutdown is not deallocation. |
| CMP-048 | The host MUST sign each bounded request over binding, boot id, writer epoch, session, generation, action id, arguments, and deadline. Local receipts MUST commit before mutations. An unresolved receipt MUST NOT be replayed. Lease loss and `ExecStopPost` MUST fence only that binding's containers. Routines MUST report `computer_not_ready` instead of starting paid compute. `get_or_create` MUST NOT create an Azure resource or start a stopped host. |
| CMP-049 | Inventory and reconcile routes MUST be administrator-only. Reconcile MUST verify absence of the host and every recorded disk and NIC before resolving. Per-bot cloud configuration MUST be rejected while a workspace compute profile is active. |

## macOS companion

These are development requirements from the approved plan. Native qualification
is tracked separately in [the evidence ledger](../metrics/macos-companion-validation.md).

| ID | Requirement |
| --- | --- |
| CMP-050 | `open_interface` MUST select an owner-paired `macos_local` provider without cloud fallback. One active bot binding and one local companion process MUST control a device. Mac bots/captures/history MUST remain owner-only and outside shared-computer mode. |
| CMP-051 | Pairing MUST use one-time expiring codes, backend token hashes and local Keychain storage. Sharing and input MUST start off, require local consent, and be fenced on session/permission/connection loss. Status/Stop IPC MUST require the same UID and a private credential. |
| CMP-052 | Selected-window capture MUST use ScreenCaptureKit without activation or desktop cropping. Whole-primary-display OI capture MUST require explicit local scope. AX identities and OCR candidates MUST remain distinct; secure and ambiguous targets MUST be refused. |
| CMP-053 | Native actions MUST require current signed permits and durable pre-dispatch receipts. Duplicate identities MUST NOT replay effects. Unknown results MUST quarantine the binding; stopping a process MUST NOT be treated as rollback. |
| CMP-054 | Input MUST be limited to the maintained action schema, fresh target geometry/focus and single-line literal Unicode. Model output MUST NOT execute shell, Python, AppleScript, clipboard or arbitrary native functions. Model credentials MUST stay in the backend. |
| CMP-055 | TaskStar submission MUST preserve producer/task identity across reconnects. Task linkage and run admission MUST commit atomically; changed input MUST conflict. Producer timeout MUST NOT replay native input. Native and live-model acceptance MUST be reported separately from portable tests. |

## Traceability

| IDs | Sources |
| --- | --- |
| CMP-001–CMP-014 | Blueprint §7; ADR-0002, ADR-0003, ADR-0004, ADR-0012 |
| CMP-015–CMP-028 | [016](../016-agent-control-backend-runtime.md); [018](../018-agent-control-backend-features-plan.md) B3–B7 |
| CMP-029–CMP-033 | ADR-0018; [023](../023-shared-workspace-computer.md) |
| CMP-034–CMP-041 | [007](../007-agent-control-ufo-runtime.md) |
| CMP-042–CMP-049 | [010](../010-agent-control-azure-runtime.md); [008](../008-agent-control-azure-compute-plan.md) |
| CMP-050–CMP-055 | [029](../029-agent-control-macos-companion-plan.md); [030](../030-agent-control-macos-runtime.md) |
