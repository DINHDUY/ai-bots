# SRS-002 Domain model and persistence

Identities, state, and the single SQLite store. Protocol shapes are in [005-protocols-and-api.md](005-protocols-and-api.md).

## Entities

| ID | Requirement |
| --- | --- |
| DOM-001 | User ids MUST be 16 hex characters. Usernames MUST be 3–32 characters matching `[A-Za-z0-9_-]` and MUST be unique case-insensitively. Passwords MUST be stored as scrypt hashes (`N=2^14`, `r=8`, `p=1`, 16-byte salt) and compared in constant time. |
| DOM-002 | A login session id MUST be 32 hex characters. Cookie `agentbot_session` MUST be `id.HMAC_SHA256(secret, id)`, HttpOnly, with a 7-day TTL. Logout MUST revoke the server-side row. A login session MUST NOT be a computer session. |
| DOM-003 | A credential MUST belong to one user. Provider MUST be `openai`, `anthropic`, or `azure_foundry`. The secret MUST be a versioned Fernet envelope. Responses MUST include only a last-4 `key_hint`. Foundry endpoints MUST be https with no userinfo, query, or fragment. Provider MUST be immutable. Delete MUST return 409 while a bot uses the credential. |
| DOM-004 | A bot id MUST be 16 hex characters. Fields MUST include name, immutable framework, instructions of at most 16000 characters, credential, and model id. The credential MUST be owned by the same user and accepted by `providers_for_framework`. |
| DOM-005 | A computer session id MUST look like `computer_…` and MUST carry a generation. Replacement MUST allocate a new id and MUST increment generation. Ids MUST NOT be reused. |
| DOM-006 | A run id MUST look like `run_…`. It MUST store the prompt, submitting principal, frozen bot config and fingerprint, trigger, status, and outcome. |
| DOM-007 | An action MUST reference one run and MUST store an immutable argument digest. An approval MUST reference that action and MUST store deadline, revision, status, and decision principal. |
| DOM-008 | Events MUST have a unique `event_id` and a per-bot monotonic `seq`. A retention floor `floor_seq` MUST make older cursors report a gap instead of a silent skip. |
| DOM-009 | Messages MUST have stable ids and ordinals. The model context MUST use the most recent 200 stored messages. Older messages MUST remain available through the history API. Only user prompts and final assistant results are memory. |
| DOM-010 | A capture record MUST point at a PNG outside SQLite. A command receipt MUST be unique on `(bot_id, request_id)` and MUST store the request fingerprint and response. |
| DOM-011 | Identity MUST separate `workspace_id`, `bot_id`, `session_id` plus generation, `run_id`, `action_id`, and `event_id` plus `seq`. The same separation MUST appear in rows, Python models, TypeScript types, and event envelopes. |
| DOM-012 | v1 MAY use the bot id as both conversation key and sandbox key. v2 MUST pass the computer id as the kernel session key, supply memory from the durable store, inject the wrapped sandbox, and let the control plane own persistence. The kernel MUST accept keyword-only `conversation_id`, `memory_context`, `sandbox`, and `persist_history`. |

## State machines

| ID | Requirement |
| --- | --- |
| DOM-013 | Run admission MUST, in one transaction, write the receipt, the run row, and the user message. States MUST include `preparing`, `running`, `awaiting_approval`, `stopping`, `completed`, `failed`, `cancelled`, and `interrupted`. Human control MUST add `paused` such that no new agent mutation dispatches. A final state MUST NOT return to `running`. A retry MUST be a new run id. |
| DOM-014 | `preparing`, `running`, and `awaiting_approval` MUST become `interrupted` on process restart. `stopping` MUST become `cancelled` only after in-flight sandbox calls drain or supervised process groups terminate. An ERROR frame, exception, or run deadline MUST lead to `failed`. |
| DOM-015 | Computer sessions MUST move `provisioning → running → closing → closed`, with `failed` when termination or recovery cannot be confirmed. Lifecycle MUST also support `hibernating`, `hibernated`, and `resuming`. A `failed` or `closing` computer MUST block new runs until closed. Health MUST be a separate observation: `healthy`, `degraded`, or `unknown`, with an observation time. |
| DOM-016 | Approval status MUST be `pending`, `approved`, `denied`, `expired`, or `cancelled`. Exactly one compare-and-set on revision, status, expiry, and run state MUST win. |
| DOM-017 | Action states MUST include `proposed`, `awaiting_approval`, `executing`, `succeeded`, `failed`, `denied`, `expired`, `cancelled`, and `outcome_unknown`. An `outcome_unknown` action MUST NOT be dispatched again automatically. |
| DOM-018 | Human control states MUST be `agent`, `waiting_for_safe_point`, `human`, and `paused`. Input MUST also require a current lease fence. |

## SQLite and transactions

| ID | Requirement |
| --- | --- |
| DOM-019 | One `Database` connection MUST serve catalog and event store: WAL, `busy_timeout`, foreign keys on, `isolation_level=None`. Two connections MUST NOT be opened against the same deployment. |
| DOM-020 | Migrations MUST be ordered SQL files under `agentbot_control/migrations/`, packaged with the backend, and applied transactionally. Downgrade-in-place MUST NOT be supported. Rollback MUST restore a consistent backup and run a compatible backend. |
| DOM-021 | A state change and its event MUST commit in the same `BEGIN IMMEDIATE` transaction. Subscribers MUST wake after commit and MUST read committed pages by sequence. A crash between commit and notification MUST NOT erase the event. |
| DOM-022 | The database worker MUST accept at most 128 queued jobs. Overload MUST surface as a retryable 503. |
| DOM-023 | Required tables MUST include `schema_migrations`, users, login `sessions`, credentials, bots, `workspaces`, `workspace_members`, `computer_sessions`, `runs`, `actions`, `approvals`, `approval_policies`, `bot_events`, `command_receipts`, `capture_records`, artifact versions, and `control_leases`. Later features MUST add their tables by migration rather than a second database. |
| DOM-024 | `bot_autopilot` MUST key on `bot_id`, store `enabled`, a monotonic `revision`, `changed_by`, and `changed_at`. A missing row MUST read as disabled at revision 0. The first real change MUST become revision 1. |
| DOM-025 | Approvals MUST be able to record `decision_source` as `manual`, `policy`, `autopilot`, or `observation`, plus a nullable `autopilot_revision`. Complete action arguments and policy constraints MUST use versioned encryption envelopes. Events MUST store sanitized display text. |
| DOM-026 | Startup MUST import legacy JSON transcripts once per bot, mark unfinished runs `interrupted`, expire pending approvals, reconcile or quarantine computers, prune retention, and only then accept commands. Legacy JSON under `SESSION_DATA_DIR` MUST remain a migration source. Raw-gateway history MUST live under `SESSION_DATA_DIR/gateway`. |
| DOM-027 | Control containers MUST be labeled with deployment, namespace, bot, instance, and generation. The raw gateway MUST use a distinct `gateway` namespace. A caller-named gateway session MUST NOT select a control-plane container. |
| DOM-028 | Legacy control containers MAY be matched only by an owned bot plus the exact old container name and session label. They MUST be stopped and retained, shown as unverified, and MUST block a new run until closed. Unmatched containers MUST NOT be adopted or removed. |
| DOM-029 | Unique partial indexes MUST enforce one active run per bot and, unless the workspace is in shared-computer mode, one live computer per bot. In shared mode the run MUST reuse the workspace computer and MUST NOT insert a bot-owned computer row. |
| DOM-030 | Blob bytes MUST live in a private directory beside `CONTROL_DB` (suffix `.blobs`), outside static assets and the SQLite file. Access MUST go through authenticated handlers. |
| DOM-031 | Admission MUST take a per-bot `asyncio.Lock`, then the receipt check, then the admit transaction. Sandbox creation MUST be shielded from cancellation. |
| DOM-032 | The sandbox MUST be wrapped in `GuardedSandbox`. On stop it MUST refuse new calls and drain in-flight calls before the run becomes `cancelled`. An uncertain Docker outcome MUST count as unverified termination. |
| DOM-033 | Each approval MUST be persisted before its frame can be answered. A decision MUST resolve the in-memory future only after the compare-and-set commits. Hot-path frame writes, capture file writes, and upload chunk IO MUST run off the event loop. |
| DOM-034 | Close MUST stop the active run, force-remove the container, wait for the run task, and record `closed`. A failed close MUST record `failed` and MUST block new runs. |
| DOM-035 | Shutdown MUST stop admitting, request stop on every run, wait up to 120 seconds, then release the process lock. Logout MUST NOT cancel already accepted v2 runs. |

## Workspace deletion

| ID | Requirement |
| --- | --- |
| DOM-036 | Only the workspace owner MAY delete a custom workspace. Personal MUST remain protected. Confirmation MUST bind the exact name, workspace ID and current preview digest. |
| DOM-037 | Logical deletion, queue removal, preference repair, tombstone and owner receipt MUST commit atomically. Active runs, claimed work, transfers, human control, nonclosed computers and uncertain outcomes MUST block deletion without changing workspace content. Late producers MUST NOT recreate deleted content. |
| DOM-038 | Local file removal MUST use durable cleanup identities and validated roots outside the catalog transaction. Outstanding files and bytes MUST remain observable until removal, including after cancellation, response loss and restart. Status and retry MUST remain owner-accessible after membership removal. |
| DOM-039 | Workspace deletion MUST preserve account credentials, unrelated workspaces, external machines and required cloud/lifecycle/import evidence. Original owners MAY inspect and reconcile retained inventory; this MUST NOT grant ordinary workspace access. Import receipt replay MUST NOT resurrect the workspace. |

See [workspace deletion](../027-workspace-deletion.md) and the
[complete persistence audit](../028-workspace-deletion-audit.md).

## Configuration defaults

| Name | Default | Rule |
| --- | --- | --- |
| `CONTROL_DB` | `data/control.sqlite` | Catalog and runtime tables |
| `SESSION_DATA_DIR` | `data/sessions` | v1 JSON memory |
| `SESSION_IDLE_SECONDS` | `900` | Idle close of a running computer with no active run |
| `EVENT_RETENTION_DAYS` | `30` | Text event retention |
| `RUN_TIMEOUT_SECONDS` | `900` | Per-run deadline |
| `APPROVAL_TIMEOUT_SECONDS` | `120` | Then deny |

## Traceability

| IDs | Sources |
| --- | --- |
| DOM-001–DOM-012 | Blueprint §§5.1–5.2; [agentbot-control-plane.md](../agentbot-control-plane.md) |
| DOM-013–DOM-018 | Blueprint §5.3; [016](../016-agent-control-backend-runtime.md); [018](../018-agent-control-backend-features-plan.md) B5–B7 |
| DOM-019–DOM-035 | Blueprint §§9.3–9.4; ADR-0008, ADR-0012, ADR-0014, ADR-0017; [021](../021-foundation-operations.md) |
