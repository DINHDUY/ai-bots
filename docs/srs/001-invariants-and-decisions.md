# SRS-001 Invariants and binding decisions

Load-bearing rules. Later files specialize them. A test must be able to fail when a rule is broken.

## Architectural invariants

| ID | Requirement |
| --- | --- |
| INV-001 | The kernel MUST NOT import or branch on a concrete agent framework. It MUST resolve an adapter by name from a registry and consume only the unified event stream. |
| INV-002 | The kernel and sandbox layer MUST NOT know users, bot ownership, or credential storage. The control plane MUST pass a server-chosen session key and an already-decrypted model config. |
| INV-003 | Adapters MUST NOT execute shell, file, or browser operations on the host. Every tool MUST map to an `ISandboxClient` method. A CLI runtime that owns its tool loop MUST run inside the sandbox. |
| INV-004 | The sandbox MUST be the isolation boundary: no host mounts, no Docker socket, non-root user, all capabilities dropped, `no-new-privileges`, resource limits, and workspace paths confined to `/workspace`. |
| INV-005 | Mutating tool calls MUST emit `approval_required` and block. A missing, unknown, or timed-out decision MUST deny. Only pure observations MAY skip approval: screenshot, zoom, cursor position, wait, and file view. |
| INV-006 | In the authenticated plane the client MUST send `bot_id`. The server MUST resolve ownership and choose the sandbox session key. A client MUST NOT be able to name another tenant's container, session file, or run. |
| INV-007 | Another user's bot, key, run, approval, or capture MUST return 404, never 403. |
| INV-008 | API keys MUST be encrypted at rest, decrypted only for one turn, never returned by the API, and redacted from persisted events. |
| INV-009 | The UI MUST show only server-reported state. It MUST NOT invent uptime, browser chrome, cursor, timestamps, step counts, plans, or publication claims. Unknown MUST display as unknown. |
| INV-010 | The default MUST be one active run per bot and one live computer per bot. The active-run rule MUST be a unique partial index, not only an in-memory set. A workspace owner MAY switch eligible Docker or Azure bots onto one workspace-owned computer. Windows and UFO bots MUST keep their own computer. |
| INV-011 | Execution lifetime MUST be independent of observation lifetime. A browser disconnect MUST NOT cancel a v2 run. Runs MUST be owned by a server-side coordinator. |
| INV-012 | Mutating commands MUST be idempotent. Every command MUST carry a `request_id`. The fingerprinted response MUST be stored atomically with the state change. |
| INV-013 | After a crash, unfinished runs MUST become `interrupted` and authorized-but-unconfirmed actions MUST become `outcome_unknown`. The system MUST NOT automatically retry them. |

## Binding decisions

| ID | Requirement |
| --- | --- |
| DEC-001 | `execute_step` MUST be an async generator. A callback SDK MUST bridge events through an `asyncio.Queue` and a sentinel. A pull iterator MUST NOT be the adapter boundary. |
| DEC-002 | `DockerSessionManager` MUST reattach by session label and MUST idle-sweep containers that are not busy. A fresh container per turn MUST NOT be the default. |
| DEC-003 | In-container helpers MUST start through `docker exec`, MUST open no ports, and MUST return JSON on stdout. Browser state MUST live in a daemon. |
| DEC-004 | Image build MUST copy `sandbox/desktop_plan.py`. Validation MUST live in that pure module and MUST be unit-tested without a display. A second planner MUST NOT exist. |
| DEC-005 | Approval timeout MUST deny. The approval MUST NOT stay pending. Routines MUST park work until a deadline instead of blocking the scheduler. |
| DEC-006 | Durable conversation memory MUST store user prompts and final assistant results only. Tool traffic MUST NOT be replayed as memory. The model MUST re-observe the sandbox on the next turn. |
| DEC-007 | The kernel MUST run inside the control process. An OS file lock beside the database MUST refuse a second control process. There MUST be no RPC layer between admission and execution. Multiple Uvicorn workers MUST NOT be used. |
| DEC-008 | Catalog and event log MUST share one SQLite database in WAL mode with a single writer. A network database MUST NOT be introduced for this deployment. |
| DEC-009 | Control-plane API keys MUST be encrypted per user. Process environment keys MUST NOT be the multi-tenant vault. The raw gateway MAY use `OPENAI_API_KEY` and `ANTHROPIC_API_KEY` only when no `ModelConfig` is passed. |
| DEC-010 | The UI MUST open one event subscription per bot. v1 frames MUST NOT be multiplexed across bots. v2 envelopes carry bot identity and still use one subscription per bot. |
| DEC-011 | The server MUST own runs, receipts, and events. Client-owned execution MUST NOT be used. Refresh and disconnect MUST NOT drop work or pending approvals on v2. |
| DEC-012 | `GuardedSandbox.drain` MUST raise when termination is unverified, including when `UncertainSandbox.uncertain` is set. Docker MUST expose `uncertain` as a property. A command that might still be running MUST NOT be treated as finished, and the next run MUST NOT share that dirty sandbox until recovery or close. |
| DEC-013 | `composition.build_services` MUST publish a frozen `Services` graph on `app.state.services`. `SandboxRouter` MUST be the single sandbox entry. Per-turn control-plane state MUST live on `streamer.context` (`RunContext`). `StoreHooks` MUST replace attribute grafting. Call sites MUST use `isinstance` against `@runtime_checkable` Protocols, not `hasattr`. `build_kernel(control=True)` MUST register `ufo`; the raw gateway MUST call `build_kernel()` without `ufo`. |
| DEC-014 | `Database` MUST own the single connection, the process lock, migrations including `000_catalog.sql`, and `Database.run` on one worker thread. `EventStore.offload` MUST use that worker. `Catalog.seal` and `Catalog.unseal` MUST be the public secret API. Request handlers MUST NOT block the event loop on that connection. |
| DEC-015 | `make check` MUST run ruff, both Pyright projects, pytest excluding Docker and Windows-desktop marks, documentation links, the core-install probe, wire-schema drift, frontend lint, production build, and unit tests. Pre-commit MUST run ruff, Pyright, line endings, and frontend `tsc`. `tests/test_architecture.py` MUST guard the kernel import boundary and forbid growth of synchronous transaction calls inside `async def`. |
| DEC-016 | A from-scratch build MUST place SQL in `repositories/`. It MUST NOT recreate a legacy SQL allowlist. Blocking database work MUST go through the worker. Package metadata MAY stay at `0.1.0`; that number is not a behavioral requirement. |
| DEC-017 | Service consumers MUST receive individual collaborators or callbacks, not the runtime object. Event and snapshot envelopes MUST be versioned and emitted by a side-effect-free exporter. The SPA MUST require protocol v2 and MUST NOT own automatic approval. Commit wakeups MUST be hints only. Cursors MUST be registered before catch-up, cleared before reading, and reconciled at least every 5 seconds. Pages and sends MUST be bounded. Unknown external side effects MUST NOT be restarted. Capacity MUST be enforced inside the reservation transaction. Database and blobs MUST be backed up together from a stopped state. Restore MUST target a new directory, write a startup fence before copying, and reconcile provider identity before activation. |
| DEC-018 | Computer mode `per_bot` MUST be the default. A workspace owner MAY select `shared`. In shared mode, eligible Docker and Azure bots MUST attach to one workspace-owned computer with `bot_id` null. UFO bots and paired Windows PCs MUST be excluded. Bot-level lifecycle of that computer MUST be rejected. Approvals, Autopilot, credentials, and transcripts MUST stay per bot. Each action MUST still take the computer action lock. The mode change MUST be refused while any eligible computer is not closed. Nothing MUST be copied between modes. |

## Resolved conflicts

These older statements are not requirements:

| Superseded statement | Requirement that wins |
| --- | --- |
| ADR-0009: rotating `AGENTBOT_SECRET` always makes stored keys unreadable | DEC-009 plus `SEC` key rules. Without `AGENTBOT_KEYRING_FILE`, the secret derives the encryption key, so changing it makes those records unreadable until offline rotation. With an explicit keyring, encryption is independent of the signing secret. Changing `AGENTBOT_SECRET` always invalidates login cookies. |
| ADR-0015: do not add CI before a remote exists | DEC-015. [.github/workflows/check.yml](../../.github/workflows/check.yml) is required. Hosted execution evidence is an operations qualification, not a reason to omit the workflow. |
| ADR-0016: `uv.lock` stays untracked; async-transaction baseline is 163 | The lockfile MUST be committed and `uv sync --locked` MUST be the install. The current tree's measured ratchet is historical. A rebuild follows DEC-014 and DEC-016. |
| ADR-0014 consequence that remaining modules stay on an allowlist | Transitional for the existing tree only. DEC-016 is the rebuild rule. |
| Blueprint v1 note that execution lives inside the socket handler | True only for the legacy facade and the raw gateway. v2 follows INV-011. |

## Pyright modes

| ID | Requirement |
| --- | --- |
| DEC-019 | Pyright MUST be strict for `agentbot` and `agentbot-computer-agent`, and for the foundation project `pyrightconfig.foundation.json`. The backend and Windows companion MUST use basic mode. These diagnostics MUST be warnings there, not errors: `reportAttributeAccessIssue`, `reportArgumentType`, `reportMissingImports`, `reportOptionalMemberAccess`, `reportCallIssue`, `reportOptionalSubscript`, `reportIndexIssue`, `reportGeneralTypeIssues`, `reportOperatorIssue`, `reportOptionalIterable`, `reportOptionalOperand`. |
| DEC-020 | Frontend lint MUST use the TypeScript 6 parser. The application compiler MUST be TypeScript 7. `npm ci` MUST use the committed peer-dependency configuration. |

## Traceability

| IDs | Sources |
| --- | --- |
| INV-001–INV-013 | Blueprint §2 |
| DEC-001–DEC-012 | ADR-0001 through ADR-0012 |
| DEC-013–DEC-016 | ADR-0013 through ADR-0016, resolved as above |
| DEC-017–DEC-018 | ADR-0017, ADR-0018, [023](../023-shared-workspace-computer.md) |
| DEC-019–DEC-020 | ADR-0015; [003](../003-agent-control-implementation-status.md); README |
