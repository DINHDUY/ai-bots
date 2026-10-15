# Agent Control runtime (B1–B11)

Azure-hosted computers use the provider and outbound bridge described in the [Azure runtime and operator runbook](010-agent-control-azure-runtime.md). Live Azure deployment acceptance remains pending; Docker and Windows remain available without Azure configuration.

Workspace bot discovery, automatic peer messaging, and reply continuations are described in the [workspace channel runtime guide](015-agent-control-workspace-channel-runtime.md). Enable collaboration per workspace and enroll bots explicitly.

B1 adds durable runs and reconnect recovery to `agentbot-control`. The existing control-plane `/ws` remains available; the frontend requires v2 through `GET /api/capabilities` and uses HTTP commands plus a validated event subscription. It has no v1 fallback. The raw `agentbot` gateway retains its existing wire protocol.

B2 adds authoritative approvals, scoped persistent rules, and structured execution outcomes for both Microsoft and Claude adapters. `persistent_policies` and `structured_actions` are enabled in capabilities.

B3–B11 add inspected computer health, full files and attachments, exclusive human input, real PTYs, lifecycle operations, workspace permissions and sharing, groups, reviewed skills, a GitHub connector, and durable routines. These run through the same authorization and action coordinator as chat.

Current foundation changes, health/admission limits, provider guarantees, key rotation and fenced restores are documented in the [operations runbook](021-foundation-operations.md). The [implementation ledger](003-agent-control-implementation-status.md) distinguishes this working tree from the tagged baseline.

## Run and upgrade

Install the existing backend development dependencies, rebuild the sandbox image, then start the control plane as one process:

```powershell
docker build -f docker/sandbox/Dockerfile -t agentbot-sandbox .
.\.venv\Scripts\agentbot-control
```

The image includes supervised shell commands, browser/Xvfb services, no-follow file operations and a watcher, input handling, and a PTY daemon. Helpers are owned by root. `agentbot.sandbox_protocol=2` still gates B2 execution; `agentbot.computer_protocol=3` gates the new computer services. Rebuilding the tag does not change an existing container. Retain needed files, then close/recreate older computers. An older image or missing helper disables the corresponding service instead of using an incompatible path. Services use private Unix sockets and Docker exec; no browser-accessible sandbox port or Docker socket is introduced.

`CONTROL_DB` contains the existing catalog and new runtime tables. Numbered migrations under `agentbot_control/migrations/` run transactionally and are packaged with the backend. Existing users receive personal workspace records. Existing owned bot transcripts are imported once, preserving content, stable imported message IDs, and unknown historical timestamps. New control-plane messages are written to SQLite; legacy JSON files remain available as migration/backup sources. Model context currently uses the most recent 200 stored messages; older messages remain available through the history API and frontend pagination.

Back up the catalog and legacy transcript directory before upgrading a populated deployment. Do not downgrade an active v2 deployment to a backend that does not understand its run state. Stop/drain work first and restore a consistent backup when rolling back.

The runtime holds an OS file lock next to `CONTROL_DB`; another process using that database fails startup. Do not configure multiple Uvicorn workers for this deployment. Login sessions remain in the original `sessions` table; sandbox instances are in `computer_sessions`.

Control containers have deployment, namespace, bot, instance, and generation labels. Raw gateway containers use a separate `gateway` namespace, and raw gateway JSON history now lives under `SESSION_DATA_DIR/gateway`. Move only known raw-gateway transcripts into that directory when upgrading a raw-gateway deployment; control-plane transcripts must stay out of that namespace.

Legacy control containers are matched using an owned bot record, its exact old container name, and its old session label. The fixed Docker identity is saved in the private catalog mapping; it is revalidated on every lookup. These containers are stopped and retained for recovery rather than automatically executing work with an old image. The UI marks them unverified and requires closure before a new run. Closing deletes their workspace, so recover any needed files before closing. Unmatched legacy containers are not adopted or removed by the control runtime.

## Execution and interruption

- A bot has a persistent `bot_id`. Each replacement computer has a fresh `session_id` and incremented generation. Every submitted turn has its own `run_id` and configuration snapshot/version.
- A v2 socket observes runs. Refreshing, switching layouts, or losing that connection does not cancel execution. A legacy control-plane socket still cancels the run it created when it disconnects.
- Both control-plane protocols use the same coordinator and transactional per-bot admission constraint. Commands have request IDs; replaying an identical accepted request returns its original receipt. Reusing an ID for another payload is rejected.
- Stop returns `stopping` first. Tracked sandbox operations must settle, or supervised shell process groups must be terminated, before the run becomes `cancelled`. Unverified termination blocks another writer and exposes a recovery/close path.
- On shutdown the runtime stops accepting work and drains active work. On restart, unfinished runs become `interrupted`, pending approvals expire, and affected computers are reconciled/quarantined. No uncertain external operation is automatically retried.
- Logout revokes that login's subscriptions. Already accepted v2 runs continue under their deadlines. Delete and Close stop owned work and confirm sandbox removal before reporting completion.

Container existence and a bound session are separate from service health. The computer endpoint probes responsive browser/Xvfb/file/PTY services without creating or starting a container. Missing inspection evidence is `unknown`; service failure in a running container is `degraded`.

## V2 endpoints

Endpoints require the existing session cookie and current workspace membership or the explicitly selected share grant. Operators need a separate bot execution grant for mutations; viewers cannot execute. Credential and policy management remain bot-owner operations. Origin checks apply to mutations and WebSockets, and long-lived subscriptions recheck login and authorization.

| Endpoint | Behavior |
| --- | --- |
| `GET /api/capabilities` | Protocol and supported capability flags; does not start a computer. |
| `GET /api/bots/{bot_id}/snapshot` | Consistent state at `snapshot_seq`: computer, latest run, recent messages/events, pending approvals, and history cursor. |
| `GET /api/bots/{bot_id}/messages?before=...` | Earlier messages, 200 at a time, with stable IDs and server times where known. |
| `POST /api/bots/{bot_id}/runs` | `{request_id, prompt}`; returns 202 and the admitted run/instance. |
| `GET /api/bots/{bot_id}/runs/{run_id}` | Persisted status, configuration reference, principal, timestamps, and outcome. |
| `POST /api/bots/{bot_id}/runs/{run_id}/stop` | `{request_id}`; accepted stop or existing final status. |
| `POST /api/bots/{bot_id}/approvals/{approval_id}/decision` | `{request_id, decision: "approve" | "deny", revision}`; acknowledged decision for a current request. |
| `GET /api/bots/{bot_id}/approval-policies` | Owned bot's saved rules, versions, expiry, creator, and revocation state. |
| `POST /api/bots/{bot_id}/approval-policies` | `{request_id, approval_id, ttl_seconds}`; derives an exact supported scope from the stored approval. Creating a rule does not approve the current request. |
| `POST /api/bots/{bot_id}/approval-policies/{policy_id}/revoke` | `{request_id}`; revokes future authorization and increments the rule version. |
| `POST /api/bots/{bot_id}/computer/close` | `{request_id, session_id}`; rejects an outdated instance and cannot close its replacement when retried. |
| `GET /api/bots/{bot_id}/events?after_seq=...` | Up to 100 committed events and a retention-gap indicator. |
| `/api/bots/{bot_id}/events/ws?after_seq=...` | Ordered replay followed by live committed events. Without a cursor, or after a retention gap, supplies a new snapshot. |
| `GET /api/bots/{bot_id}/captures/{capture_id}` | Private retained PNG bytes; unavailable/expired captures return 404. |

Commands accept request IDs containing letters, digits, underscores, and hyphens, 8–128 characters long. Prompts are limited to 32,000 characters. A lost HTTP response does not cause an automatic command retry on reconnect; the frontend retains the request ID for an explicit retry and reconciles state through a snapshot.

Events use schema version 2 and include event ID, per-bot sequence, workspace/bot/instance/generation, run/action references, and server occurrence time. State and its event are committed in one transaction. Subscribers read bounded pages from the committed log, so a disconnect or a commit-before-publish interruption does not lose the event. The client deduplicates replay and enables commands after catch-up. Slow sends time out rather than accumulating an unbounded in-memory queue.

## Autopilot

Autopilot is a persistent, per-bot approval mode, off by default. The bot owner can enable it in **Bot settings** or the **Live Cloud Computer** controls, including before a computer exists. Enabling it approves valid pending and future requests through the shared dispatcher, without an open browser. It covers both agent adapters, skills, connector requests, scheduled runs and group handoffs. Each target bot uses its own setting.

`GET /api/bots/{bot_id}/autopilot` returns `enabled`, `revision`, `changed_by`, `changed_at`, and caller-specific `can_manage`. `POST` accepts `{request_id, enabled, expected_revision}` and requires the bot owner. Current workspace members can read; an operator still needs an execution grant to run the bot. Writes use the existing Origin checks. Identical retries return their receipt; stale revisions and changed payloads under a reused request ID return 409. Same-value updates with the current revision do not increment it.

Migration `012_autopilot.sql` adds bot settings and approval decision attribution. Setting changes, pending decisions and the command receipt commit together with `bot.autopilot.changed`; waiters wake after commit. Snapshots and ordered events synchronize tabs, and the UI ignores older setting revisions. Auto-approved requests emit a decision without a false pending notification, retaining the enabling owner and setting revision in action history.

Turning Autopilot off cancels its authorizations that have not claimed execution. The dispatcher checks the setting revision immediately before claiming an action, so disabling and re-enabling cannot revive an old grant. Executing actions can finish; Stop remains available. Existing manual decisions and exact policies apply again while off. An approval is separate from successful execution: the UI shows **Auto-approved by Autopilot** alongside the actual result.

Autopilot takes precedence over a routine's selected approval policy. Policy availability gates new routine admissions when off; already admitted actions retain their individual authorization checks. Membership, credentials, connector versions, action arguments and file/context revisions, computer generations, human-control pause, and resource/time limits still apply. Toggling does not submit or resume work. Reset, hibernate, closure and restart preserve the setting; restart still interrupts unfinished runs without resubmitting them.

Restart the control backend to apply migration 012 and serve the rebuilt frontend. This extension requires no sandbox image change and does not alter raw-gateway approval behavior.

## Authoritative approvals and rules

Each approval stores its run, generation, action ID, immutable argument digest, deadline, revision, status, and decision principal. Complete action arguments and policy constraints use versioned encryption envelopes; events and rule summaries use sanitized display text. Retain every required encryption key when moving the database. Follow the [rotation and recovery runbook](021-foundation-operations.md).

Decisions accept `expected_revision` (or the compatible `revision` name). A compare-and-set transaction commits `approval.resolved` before `action.started`. Identical repeated decisions return the existing decision, including with another request ID. Stale revisions, expired requests, and conflicting decisions return HTTP 200 with `accepted: false` and the current status/revision. A request ID reused with a different payload still returns 409. Foreign IDs return 404.

The server rechecks context before accepting approval and again at dispatch. Timeout, stop, interruption, and a replaced generation make requests inactive. Two competing decisions or timeout/decision races have one winning transition. Policy expiry/revocation is checked again when an action claims dispatch; revoking a rule does not roll back an already executing action. Runs are not resubmitted after restart.

Supported rules are created from a pending or approved action, with a lifetime of 60 seconds to 30 days (UI choices: one hour, one day, seven days):

| Operation | Stored scope |
| --- | --- |
| Shell | Exact command text and a SHA-256 revision of the complete bounded workspace. Any workspace content, path, or permission change prevents a match, including changed scripts. No substring, regex, or category grants. |
| File write/edit | Confined workspace path, exact mutation arguments/content digest, and expected prior file revision (including `missing`). |
| Browser open | One canonical HTTP(S) origin. Navigation and redirects to another origin are blocked before a target request; subresources are not an egress firewall. Browser clicks and desktop inputs still require approval. |

Workspace revisions are limited to 2,000 entries and 64 MiB read. A tree that cannot be safely bounded/hashed, including symlinks or special files, cannot receive a persistent shell rule; its shell actions require individual approval. Checked agent text writes are limited to 64 KiB and reject paths traversing symlinks. General uploads and downloads use the separate bounded binary file service described below.

Rules apply on the server without an observer. Both adapters, handoffs, skill replay, connector calls, and scheduled work share the dispatcher. With Autopilot off, routines can use only the explicitly selected policy; without one they require human approval, as do group children without an applicable authorization. Owner-enabled Autopilot supplies automatic decisions for that target bot. Old page-local Always allow grants are never imported.

## Execution outcomes and progress

`CommandResult` records command ID, exit code (nullable when unknown), stdout/stderr, per-stream truncation, timeout/cancellation, and timestamps. The supervisor bounds each output stream to 16,000 bytes, enforces deadlines even after output descriptors close, and terminates the shell process group on cancellation. Both adapters retain a text rendering for model tool responses; Claude marks a nonzero result as a tool error.

The durable `action.started`, `action.completed`, and `action.failed` events come from the operation boundary, with run/action IDs and optional plan step IDs. Legacy `TOOL_CALL` text does not establish an execution outcome. Stop waits for sandbox work to settle; interruption with an unknown execution result remains explicitly unknown. A completed model run can contain failed actions, and `run.finished.failed_actions` reports that count.

Approval cards show submitting, decision accepted, executing, and result separately. Terminal output displays exit status, timeout/cancellation, and truncation. Activity records policy ID/version for automatic authorization. **Save an approval rule** shows the exact supported scope and expiry; **Bot settings → Server approval rules** lists and revokes rules.

Adapters may emit `emit_plan(engine, steps)` with unique step IDs, titles, and explicit statuses; those become `plan.updated`. No plan is inferred from model prose or tool counts. The default adapters do not generate a synthetic plan. Exit zero and a completed run never establish cloud publication; that requires a dedicated verified result from a future integration.

## Retention and presentation

`RUN_TIMEOUT_SECONDS` defaults to 900. `APPROVAL_TIMEOUT_SECONDS` remains 120 and `SESSION_IDLE_SECONDS` remains 900. `EVENT_RETENTION_DAYS` defaults to 30. Captures default to a seven-day rolling retention window; owners can configure count, storage, and age limits in Workspace settings > Storage. `WORKSPACE_BLOB_LIMIT_BYTES` sets the shared capture/artifact ceiling (256 MiB by default); each PNG is limited to 4 MiB. Text event fields are bounded to 64,000 characters. Capture bytes live in a private directory beside `CONTROL_DB` with a `.blobs` suffix, outside static assets and SQLite.

Snapshots contain the latest 200 messages, up to 500 retained events, the latest run's most recent 200 action/approval projections, and its explicit plan if supplied. Current action results and plans survive event retention. Older messages can be loaded in the conversation. The session context indicates when observation history is partial. The UI retains at most 30 displayed captures; the authenticated capture history API provides bounded older pages.

Known model keys and credential-bearing URL fields are filtered before run/event persistence. Protected configuration artifact previews are omitted on the server. These rules do not guarantee detection of arbitrary encoded secrets or secret material in screenshots. Captures remain owner-authorized and are served with private/no-store headers.

## Verification

```powershell
.\.venv\Scripts\python -m pytest -m "not docker"
.\.venv\Scripts\python -m pytest -m docker
npm run test --prefix packages/agent-control-frontend
npm run test:e2e --prefix packages/agent-control-frontend
```

Coverage includes migration/import, refresh and multiple observers, duplicate and competing commands, v1/v2 exclusion, approval expiry on restart, retained-history gaps, revoked subscriptions, sandbox generation changes, and process-lock exclusion. Docker checks execute supervised commands and verify that stopping through the control API prevents a delayed workspace write. Browser checks verify v2 refresh/reconnect and retain the existing workspace/responsive tests. These checks use deterministic model fixtures and do not invoke a cloud model or publish cloud data.

B2 coverage adds both real adapters, nonzero exit versus timeout, structured output/correlation, decision/timeout races, changed context, stale generation/revision, duplicate/conflicting decisions, foreign approval/policy access, argument/script changes, policy expiry/revocation at dispatch, file scopes, origin matching, and model failures. Docker checks verify bounded output, revision enforcement, no-follow writes, and blocked cross-origin redirects. Frontend tests verify saved-rule creation/revocation and a browser flow from submission through accepted decision, execution, failed result, and refresh recovery.

## Computer services and bounds

`CONTROL_WORKSPACE_FEATURES=1` enables B3–B11 routes, observation, and automation. Set it to `0` to advertise those capabilities as disabled and stop new scheduled dispatch; B1/B2 readers, run recovery, and cleanup remain active. This is a rollout switch, not a database downgrade. Per-computer capabilities additionally check the image, service availability, and current user's permissions.

| Service | Contract and defaults |
| --- | --- |
| Health | `GET /api/bots/{bot_id}/computer`; inspect-only, independent service probes, actual Docker start time. `HEALTH_POLL_SECONDS=10`, 30-second stale threshold, six-second inspection timeout. Viewers and probes do not extend idle lifetime. |
| Captures | `POST /api/bots/{bot_id}/captures?surface=browser|desktop`, latest/history GETs. PNG up to 4 MiB, 4096 pixels per dimension/16 megapixels, on-demand interval at least 0.5 seconds. Observed computers receive periodic browser captures. Metadata carries surface, epoch, sequence, viewport revision, dimensions, sanitized URL/title, and observed cursor when available. Historical/cropped captures are view-only. |
| Live files | Session routes `/files`, `/file-preview`, `/file-content`, `/uploads`. Listings page at 200 entries; previews at 64 KiB; complete binary uploads/downloads at 64 MiB. Downloads require the expected revision. Paths are confined by no-follow descriptor-relative opens under `/workspace`; symlinks and special files are rejected. |
| Retained outputs | `/api/bots/{bot_id}/artifacts/{id}/content` returns an immutable version with attachment/nosniff headers. Captures and files share the workspace ceiling set by `WORKSPACE_BLOB_LIMIT_BYTES` (256 MiB default). Retained files keep their seven-day expiry; screenshot retention is independently configurable. Agent file-artifact events retain up to 20 output versions per run; a bash-only output is discoverable through the file watcher and can be retained by downloading it. |
| Uploads | Multipart fields include request ID, path, expected revision (`missing` for a new file), and file bytes. Successful retries preserve the upload ID. The run accepts up to ten explicit attachment IDs and verifies owner, instance, and current revision. Stop agent work and release human control before uploading. If the server fails after a native commit, inspect the live revision before issuing a new upload. |
| Watcher | Coalesced inotify observations plus periodic rescan, bounded to 10,000 entries/1,000 watches. Overflow/restart requests a relist. These are invalidations, not a complete write audit. |
| Human control | Session `/control/acquire`, `/renew`, `/release`, `/resume` and `/control/ws`. Lease lifetime 30 seconds, UI renewal every ten seconds; login, tab, generation, fence, latest capture, viewport and sequence checked on input. The agent is stopped/drained before takeover and remains paused after release or lease loss. Resume starts a fresh turn that reobserves state. |
| PTY | Session `/terminals` GET/POST, `/{id}/close` POST, `/{id}/ws`. Real Bash PTYs; one per lease/two per workspace, 256 KiB replay, 4 KiB input chunks, 32 KiB/s websocket input, 200 rows/400 columns maximum. Five-minute idle and one-hour maximum lifetime. Disconnect closes the PTY and its job-control groups; replay offsets/gaps are explicit while a PTY remains open. Clipboard escape sequences are disabled. |
| Lifecycle | `POST /api/bots/{bot_id}/lifecycle/{create|close|reset|hibernate|resume|keep-warm}` with request ID and generation. The journal records completion only after reconciliation; interrupted operations are not automatically repeated. Keep-warm is at most 120 minutes and two computers per owner. Idle close defaults to 15 minutes with a one-minute warning. |

A workspace owner can switch that workspace to one shared computer. `GET` and `PUT /api/workspaces/{id}/computer` read and change the mode; `POST /api/workspaces/{id}/computer/lifecycle` creates, closes, resets, hibernates, resumes, or keeps the shared computer warm. Eligible bots are Docker sandbox bots and Azure cloud bots. Microsoft UFO bots and bots paired with a Windows PC keep their own computer. Shared mode is refused with `computers_active` while any eligible computer is still open, and nothing is copied across the switch. Bot lifecycle routes then return `workspace_computer`. Workspace lifecycle returns `computer_busy` while a run or human lease is using the shared computer. Runs may overlap; each action still takes that computer's lock. One human lease pauses every attached bot. The shared computer counts once toward capacity and is charged to the workspace owner. State events are written to every attached bot. See [023](023-shared-workspace-computer.md).

Hibernate stops the container and retains `/workspace` for seven days. It does not preserve a running agent, shell, browser page, or `/tmp`. Resume reprobes services and changes the surface epoch/fence; the agent remains paused. Reset removes the old container and creates a new generation. A failed provision is marked failed with its operation step, and cannot accept another run until reconciled/closed.

General file APIs expose only metadata for protected configuration names such as `.env`, credential files and private key extensions. They cannot be uploaded, previewed, downloaded, shared, or text-indexed through this flow. Filename rules and URL sanitization are not general secret detection. Teaching private mode suppresses recorded input and captures while enabled; the owner still needs to review recorded steps and selected shared surfaces.

## Workspaces, groups, and reusable tools

`/api/workspaces` lists/creates workspaces; workspace members are owner/operator/viewer. Existing users retain their personal workspace. Owners explicitly grant each operator credential-backed execution through `/api/bots/{id}/execution-grants`. Viewers can inspect workspace content. Bot moves between workspaces are deliberately unsupported because credentials and retained resources need reassignment rules.

`/api/preferences` persists selected workspace, avatar/display label, sidebar order/folders, read cursors, and onboarding with revision compare-and-set. `POST /api/bots/{id}/read-cursor` advances the current user's message position monotonically and merges it without overwriting other preferences. `/api/notifications` provides durable, deduplicated, paginated read history. Workspace `/search` uses SQLite FTS and current membership for bot/message/skill/routine metadata and eligible retained filenames. Arbitrary file contents are not indexed. `/diagnostics` exposes owner-only active-run/approval counts, health age, storage quota, stream sequence floors, releasing leases, computer state and scheduler backlog.

Owners create expiring view-only shares under `/api/bots/{id}/shares`, selecting browser/desktop surfaces and/or retained artifact IDs. Recipients must be registered and authenticated. A share URL confers no access by itself, and sharing a live surface reveals its visible contents. Revocation/expiry is checked on every fetch and download chunk. The frontend polls selected shares; bot execution and general bot access are not granted.

Workspace groups maintain a separate durable conversation and member list. Tasks must explicitly mention `@group` or stable `@bot_id` values. Handoffs preserve source/target run references and correlation, recheck execution grants, and run through ordinary approvals. Limits: eight total targets, three hops, one-hour maximum deadline, one active child per group, 8 KiB explicit context, and five selected UTF-8 artifact versions of at most 64 KiB each. Removed members, cancellation, cycles, and expired parent work cannot create new child execution. Each bot keeps its own computer, approvals, files, and credentials.

Teach a Task requires a human lease. Start/pause/private/stop recording from the computer controls, review/delete/edit structured steps, define string parameters, and save an immutable skill version. Coordinate recordings are marked fragile; URL/viewport drift or unsupported checkpoints stop replay. Terminal activity creates a manual-review checkpoint and pauses recording; terminal input is not stored. Install reviewed skill versions on other bots in the same workspace. Replay requires a released lease and explicit resume of a paused computer, then normal action approvals.

The curated catalog currently contains **GitHub repository issues, manifest version 1**. Use a fine-grained PAT limited to one repository, Metadata read and Issues read/write. The backend encrypts it through the versioned vault; it never enters the sandbox or public events. Connect, health, list issues, create issue, rotate, local revoke, and uninstall are implemented. Both adapters can invoke installed `github_issues` tools through the shared action arbiter. Approval binds connection version, repository, operation and exact arguments; rotating/revoking prevents subsequent use of an approved old version. Local revocation removes this app's token; revoke the PAT at GitHub to invalidate it for other applications. OAuth, arbitrary MCP endpoints, public packages and billing are not offered in the catalog.

## Routines and triggers

Workspace `/routines` and `/api/routines/{id}` manage immutable versions; `/run`, `/history`, `/webhook-secret` and `/api/routines/preview` provide admission, history, rotation and next-occurrence preview. Definitions select a bot or group, task or installed skill/connection, optional exact approval policy, budget, and explicit permission to resume a hibernated computer. Single-bot jobs and group children use the normal runtime. A disabled/superseded definition cannot admit new work; already admitted jobs remain visible and subject to current authority.

| Trigger/limit | Behavior |
| --- | --- |
| Interval | 60 seconds to 30 days, preserving the original schedule phase across missed occurrences. |
| Daily | IANA timezone and local HH:MM. Skip nonexistent spring-forward times; use only the first occurrence of a repeated fall-back time. |
| Missed runs | `skip` skips a due occurrence older than 60 seconds; `latest` coalesces to the most recent due occurrence. No unbounded backlog replay. |
| Overlap/budget | One run per bot; explicit skip or queue, bounded by a 30–900 second job budget. At most 100 active routine definitions and 64 claimed/running jobs per workspace. |
| Webhook | `POST /api/webhooks/{id}`; HMAC-SHA256 of `timestamp.delivery_id.raw_body`, with `X-Agent-Timestamp`, `X-Agent-Delivery`, `X-Agent-Signature`. Five-minute timestamp window, 64 KiB body maximum, validated `{data: {...}}` task payload. Delivery IDs deduplicate across definition edits; secret rotation invalidates the prior secret. |
| Event | Single-bot `run.completed` or `artifact.retained`, with source event/run correlation. Routine/handoff output cannot trigger another routine: depth is capped at one. |
| Group | Manual, interval/daily and webhook tasks with explicit mentions. Children use each target bot's approval mode; owner-enabled Autopilot allows unattended decisions. Group policy selection and group event triggers are not exposed. |

Trigger claims and command receipts survive restart. Recovery binds an already admitted run/handoff before considering another dispatch, and reports interrupted/unknown outcomes instead of repeating external effects. Credentials, connections, memberships, installed versions and action authorization are rechecked. With Autopilot off, the absence of an online operator does not supply approval. The frontend shows routine history and durable completion/failure notifications; onboarding links to real credential, bot-creation and task-submission flows and stores completion/dismissal per user.

## Upgrade, backup, and recovery checklist

1. Drain/stop active work. Stop the single control process before taking a consistent backup of `CONTROL_DB`, its `.blobs` directory, legacy transcript sources, and the existing encryption secret. Use SQLite's backup API for online database copies; copying only a live database file can omit WAL transactions.
2. Install backend dependencies (including `httpx` and `tzdata`), build the sandbox image from the repository root, and deploy the new backend with `CONTROL_WORKSPACE_FEATURES=0` first when staging a rollout. Migrations 003–011 add services, blobs, leases, PTYs, lifecycle operations, workspaces, groups, toolkit, and routines. Migration 008 removes the personal-workspace-only uniqueness constraint and validates foreign keys.
3. Verify the copied store with `PRAGMA integrity_check` and `PRAGMA foreign_key_check`, then start it in an isolated deployment with the same secret. Confirm owned transcripts and grants before enabling new features. Startup removes abandoned host transfer staging and missing/orphan retained blobs; uncertain runs are interrupted and leases are revoked/cleaned up.
4. Enable features and recreate older sandbox instances after retaining needed files. Verify inspected protocol-3 capabilities before using input, file or PTY controls. Never reuse a production Docker deployment identity for a restore test.
5. Roll back by draining work and restoring a consistent backup with a compatible backend. Do not downgrade migrations in place or run an old binary against active new state. The feature switch disables new entry points without undoing persisted records.

The [implementation record](003-agent-control-implementation-status.md) lists executed checks and external integration limits. Local Docker tests use real container services; GitHub tests use controlled HTTP responses, and do not establish access to a live repository or Azure storage.

## Microsoft adapter performance

The [Autopilot performance implementation](011-agent-control-autopilot-performance.md#implemented) adds bounded conversation history with preserved message roles, explicit resume intent, and exact file patches. The reusable daily Blob orders tool is an explicit opt-in in an individual bot's Instructions; shared defaults contain no ETL workflow guidance. These adapter improvements apply with Autopilot on or off. The implementation also documents `run.metrics` timing events, text batching, shared Docker health inspections, and the narrow checked-action optimization that retains dispatch authorization and stale-target checks.

## Per-bot tools

The [tool libraries runtime](013-agent-control-tool-libraries-runtime.md) documents migration 015, atomic tool selection in New bot and Settings, pinned run bindings, and removal fences. Bot instructions define roles; they do not install tools.

See [screenshot retention configuration and recovery](019-agent-control-capture-retention-runtime.md) for quota thresholds, oldest-first cleanup, and missing-image history behavior.
