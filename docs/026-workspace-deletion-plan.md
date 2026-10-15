# Delete a workspace

Status: D1-D4 implemented and locally qualified on 2026-10-12. See the
[runtime guide](027-workspace-deletion.md), [table/producer audit](028-workspace-deletion-audit.md),
and [implementation evidence](003-agent-control-implementation-status.md).

Updated 2026-10-12. Add deletion of a user-created workspace, including an imported
Markdown workflow, through Workspace settings. Build on the
[implementation ledger](003-agent-control-implementation-status.md),
[workspace channels](015-agent-control-workspace-channel-runtime.md),
[shared computers](023-shared-workspace-computer.md), and
[workflow import](025-markdown-workflow-import.md).

## Scope and decisions

| Concern | Approved behavior |
| --- | --- |
| Permission | Only the workspace owner can preview or request deletion. Operators and viewers cannot delete it. |
| Contents | Delete all workspace bots, conversations, Bot channel history, groups, routines, bot-owned configuration/tools, captures, uploads, and artifacts. Empty workspaces are also supported. |
| Personal workspace | Protect the system-created `personal_<user_id>` workspace. It remains the fallback for navigation and bot creation. |
| Active work | Block deletion while runs, claimed jobs, transfers, computer operations, or human control are active or their outcomes are uncertain. Show blockers and existing controls for resolving them. |
| Computers | Require every per-bot and shared computer to be closed or verifiably retired. Hibernated, stopped-but-attached, disconnected, and failed sessions are not automatically safe. |
| Queued work | Cancel unclaimed deliveries, handoffs, jobs, and waiting continuations in the deletion transaction; remove routines so they cannot start later. |
| Account resources | Keep users, login sessions, API credentials, installed tool packages, and other workspaces. Remove bot-owned connector secrets with their bots. |
| External resources | Preserve paired Windows machines, Azure machines/storage, and recovery inventory. Workspace deletion does not issue provider resource deletion commands. |
| Recovery | Keep a minimal workspace tombstone, deletion receipt, required lifecycle/cloud/import receipts, and cleanup records. Ordinary workspace content becomes inaccessible at database commit. |
| Undo | No application undo. Existing protected backups follow the separate [restore runbook](021-foundation-operations.md); this feature does not erase backups. |

The first delivery supports nonempty, idle workspaces without requiring individual
bot deletion first. Bot moves, archival, account deletion, forced task termination,
and automatic Azure resource destruction are outside this scope.

## Existing boundaries

| Code / data | Required work |
| --- | --- |
| `workspaces/http.py` has list/create/member routes but no workspace delete. | Add preview and durable deletion routes in a separate feature module. |
| `repositories/workspaces.py` creates Personal workspaces idempotently and uses positional inserts. | Protect Personal identity, add explicit insert columns, and exclude tombstones from active queries/backfills. |
| `app/http.py` deletes one bot through channel retirement and computer close. | Reuse/extract transaction-aware primitives; do not call a sequence of bot HTTP endpoints. |
| `shared_computers/removal.py` blocks deletion of a busy shared-mode bot. | Check all bots, computer generations, and shared sessions across the workspace. |
| Migrations `001`-`020` mix cascades, restrictive foreign keys, and records without live references. | Inventory every table and define dependency order; a single workspace/bot delete does not remove all content. |
| `capture_storage` survives bot deletion; artifact and legacy session files are outside SQLite. | Record physical cleanup identities before parent deletion; extend durable cleanup to every stored file category. |
| `cloud/http.py` authorizes inventory through workspace membership. | Preserve a narrow owner recovery path after normal membership is removed. |
| `WorkspaceCenter.tsx` combines local, URL, preference, and list selection. | Clear stale selections and caches after deletion, including other tabs. |
| Import receipts replay historical creation results. | Keep receipts and make import recovery recognize a deleted workspace without recreating it. |

Use a flat backend domain such as `workspace_deletions/` with schemas, preview,
service, cleanup, and HTTP modules; put SQL in repository helpers. Inject narrow
typed collaborators through composition. Keep this feature outside the kernel and
keep Python below the 450-active-line extraction threshold.

## User flow

1. Place **Delete workspace** at the bottom of Workspace settings, collapsed by
   default. The expanded section offers deletion only to the owner and explains
   why Personal workspace deletion is unavailable.
2. Show a preview with the workspace name, bots, affected members, conversations,
   channel history, groups/routines, and stored file counts/bytes. Explicitly list
   retained external machines and recovery links.
3. Show blockers with links to existing task, computer, lease, or recovery controls.
   A rejected deletion leaves configuration, participation, and queued work intact.
4. Require the exact workspace name before enabling **Delete workspace and
   contents**. Bind confirmation to workspace ID and preview digest; duplicate
   names cannot select another workspace. Only the signed-in owner confirms this
   action; bots, imported frontmatter, and Autopilot cannot authorize it.
5. Submit once with a durable request ID. After response loss, offer **Check deletion
   status** and retry with the original ID; never silently generate a new one.
6. After catalog commit, navigate to the owner's Personal workspace. Show
   **Workspace deleted; file cleanup pending** until physical cleanup completes.
   Failed cleanup stays visible with status/retry controls.
7. Add a compact owner-only deletion history for receipt recovery, unfinished
   cleanup, and retained cloud inventory. Store counts/status, not copies of private
   instructions or conversations.

## API contract

Use strict typed models and derive JSON schemas/TypeScript through the existing
side-effect-free contract export and drift checks.

| Endpoint | Behavior |
| --- | --- |
| `GET /api/workspaces/{wid}/deletion-preview` | Owner-only read-only inventory, blockers, retained resources, and `preview_digest`. |
| `POST /api/workspaces/{wid}/deletions` | Accept `request_id`, `preview_digest`, and `confirm_name`; atomically delete catalog content and persist receipt/cleanup work. Return 202 while cleanup is pending, or 200 when complete. |
| `GET /api/workspace-deletions/{request_id}` | Owner-scoped receipt/status, accessible after the workspace is deleted. |
| `GET /api/workspace-deletions` | Paginated owner-scoped recovery/history list. |
| `POST /api/workspace-deletions/{request_id}/retry-cleanup` | Owner-only idempotent retry of the original operation's failed local cleanup items; never repeats catalog deletion or creates a new operation. |

The response includes workspace identity, logical deletion time, removed counts,
cleanup status (`pending`, `needs_attention`, or `complete`), and retained-inventory
links. Complete means recorded local cleanup finished; explicitly retained audit
and external resources are outside that count.

Key receipts by `(owner_id, request_id)`, with a canonical fingerprint of workspace
ID and command fields. Replay the receipt before checking active membership.
Changed input under the same ID returns 409. Different IDs racing to delete one
workspace yield one deletion; the second owner request receives a conflict with
the existing operation ID. Unauthorized requests use the existing non-disclosing
404 behavior, including status and retained-inventory lookups.

Build the preview digest from identities, relevant revisions, membership,
counts/stream sequences, and computer generations. Exclude private bodies/secrets
and volatile health timestamps. Recheck inventory and all blockers inside the
write transaction. Return `preview_stale` if impact changed; use structured blocker
codes such as `runs_active`, `computers_active`, `control_active`,
`transfers_active`, and `recovery_required`. Neither the digest nor typed name
replaces server authorization.

Invalid input or a confirmation-name mismatch returns 422. The deletion command
rejects the Personal workspace with `workspace_protected` (409). Cleanup retries
retain attempt history, respect worker claims, and return current status when an
item is already in progress or complete.

## Persistence, races, and deletion

Add the next migration after `020_workflow_imports.sql`, provisionally
`021_workspace_deletions.sql`; confirm its number before implementation. Add
`workspaces.deleted_at`, independent deletion receipts/status, and durable cleanup
items with server-generated resource IDs, attempts, retry times, and bounded error
codes. Reuse capture cleanup where possible; each file has one authoritative worker.

Retain the workspace row as a minimal tombstone to preserve cloud-binding and
lifecycle-receipt references and prevent identity resurrection. Remove its normal
membership/content/settings and exclude it from workspace selection, search,
scheduling, and access. Update positional inserts and initialization/backfills so
restart never recreates channels or settings for deleted workspaces.

Before enabling deletion, inventory and gate every producer: manual and legacy/v2
starts, routines/webhooks, handoffs, channel deliveries/continuations,
approvals/retries, lifecycle operations, file transfers, capture reservations, and
human-control acquisition. Final admission/claim must check an active workspace in
the same database transaction as its write. Prefetched jobs recheck before
dispatch. In-flight file writers remain observable until settled; cancellation is
not proof of rollback. Fence producers that currently perform effects before
recording admission. UI checks and in-memory task maps alone are insufficient.

Use one database-worker transaction for logical deletion:

1. Check owner, protected identity, receipt, preview, bot ownership, all active work,
   computer generations, and uncertain actions/jobs. Reject unexpected foreign-owned
   bots rather than silently extending workspace-owner authority.
2. Snapshot cleanup targets before cascades erase their identities. Verify that
   provider bindings are inactive and enrollment/control credentials cannot admit
   further work. Pending or uncertain cloud cleanup remains a blocker.
3. Mark the workspace deleted; revoke shares/execution grants, disable routines and
   enrollment, and cancel unclaimed automation work.
4. Remove content in verified foreign-key order: channel dispatch checks/deliveries,
   continuations/context, artifact grants, messages/threads, directory tombstones,
   cursors/events/settings; routine jobs before routines; groups/handoffs; bots and
   their dependents; closed shared computer/control/retention rows; unused settings.
5. Explicitly remove orphan-prone search projections, notifications, installations,
   and references without foreign keys. Keep the minimal lifecycle/cloud evidence
   required for existing retry/recovery contracts.
6. Repair affected users' preferences: select their Personal workspace when needed,
   remove deleted bot IDs from order/folders/read cursors, increment revisions, and
   preserve unrelated preferences.
7. Persist the receipt and cleanup work; commit, then notify listeners. A failure
   rolls back content, participation, preference, and queue changes together.

The implementation table audit must classify every table as removed, retained, or
unrelated, including tool libraries, compute profiles, provider inventory, and
records keyed only by historical bot/run IDs. Assert `PRAGMA foreign_key_check` in
migration/deletion tests. Atomic database deletion does not imply atomic filesystem
or provider effects.

## Physical cleanup and retained resources

After commit, remove artifact blobs, captures/temporary captures, upload staging,
and legacy per-bot session/transcript files in bounded, restartable worker batches.
Use recorded server IDs and validated storage roots; reject links or resolved paths
outside those roots. Never recursively delete a path derived from a workspace name
or imported filename. Already missing files count as removed. Keep storage/quota
accounting until physical removal is confirmed. Disk errors retain retryable work
and visible status after membership deletion.

Register cleanup with startup recovery and worker/readiness diagnostics. Resume
committed items after client cancellation or restart. Keep filesystem/provider I/O
outside database transactions and off the event loop. Preserve receipts and pending
work according to the [operations runbook](021-foundation-operations.md); do not
expire uncertain cleanup to report success.

Keep inactive Azure bindings, resource inventory, profile snapshots, and required
operation receipts under their existing recovery policy. Disable workspace compute
profiles for new use and preserve data needed for reconciliation. Allow the
original owner to use existing inventory/reconcile endpoints on tombstoned
workspaces through a dedicated recovery authorization check. Deletion history
provides the link. This exception grants no ordinary workspace access, new compute,
or bot execution. Workspace deletion never calls Azure resource deletion or deletes
working files on attached Windows/Azure machines.

Keep `workflow_import_receipts` unchanged. Replaying an import returns its original
result without recreating bots or workspace. Import recovery checks that the
workspace remains active; otherwise show **This imported workspace was deleted**
and avoid selecting or navigating to it. A deliberate new import uses new IDs.

## Frontend and transport

Put dialog/history/status components in `features/workspace-deletion/`; keep
`WorkspaceCenter.tsx` as the settings shell. Use generated contracts and TanStack
Query. Invalidate/remove affected workspace, bot, channel, computer, group, routine,
notification, and search caches after deletion. Resolve selections only against
accessible workspace IDs, covering local state, URL parameters, saved preferences,
and deletion in another tab. Handle stale 404/409 routes. Preference-save errors
must not retry the deletion command.

Notify/close affected live views after commit and enforce deletion in replay,
snapshots, shares, captures, artifacts, and streaming reads. Cached membership
must not preserve access beyond the established permission reconciliation boundary.
Reuse protocol v2; regenerate contracts if implementation changes wire events.

## Delivery and acceptance

| Milestone | Work | Completion evidence |
| --- | --- | --- |
| D1: Contract and ownership | Table/producer inventory, migration, preview, strict models, Personal protection. | Populated upgrade/restart tests, owner isolation, preview accuracy, contract drift gate. |
| D2: Deletion and recovery | Admission fencing, atomic content removal, receipts, physical cleanup, preference repair, retained inventory access. | Rollback, race, retry, restart, cleanup failure, and orphan checks. |
| D3: UI | Confirmation, blockers, recovery/history, stale selections, deleted-import handling. | Unit/browser checks for permissions, response loss, multiple tabs, desktop/mobile. |
| D4: Qualification | Integrated computer/storage checks, runtime guide, SRS updates, implementation ledger. | Required gates pass with local, mocked, and live evidence distinguished. |

Required scenarios:

1. Delete empty and populated/imported workspaces. Protect Personal, other owners,
   operators/viewers, account credentials, and another workspace's resources.
2. Populate every content category and verify the table inventory, preferences,
   storage removal, retained receipts/inventory, and foreign-key integrity.
3. Cover active/awaiting-approval/stopping runs, queued versus claimed work, waiting
   continuations, transfers, human leases, shared/per-bot computers, and uncertain
   outcomes. Rejected deletion must change nothing.
4. Race deletion with creation/editing, dispatch, uploads/captures, lease acquisition,
   and computer creation. Work serializes before deletion or is rejected afterward;
   no late writer or claimed job may recreate content beneath the tombstone.
5. Inject failure after queue cancellation, content deletion, preference repair,
   and cleanup-plan insertion. Assert rollback and no premature physical deletion.
   Exercise identical/different request IDs, response loss, cancellation, and restart.
6. Interrupt cleanup, deny filesystem access, remove files early, and use symlink
   targets outside storage. Verify retries, accounting, and unrelated-file protection.
7. With real Docker, close per-bot/shared computers, delete workspaces and local
   content, and preserve an unrelated computer. Mocked Azure checks prove retained
   inventory remains owner-recoverable with no resource deletion calls. Run native
   Windows checks for changed companion/lease paths.
8. Revoke shares/sockets; test stale routes and other tabs. Replay old imports without
   resurrection. Browser tests cover name confirmation, blockers, mobile layouts,
   pending/failed cleanup, and reload recovery.

Keep tests outside production source. Run changed Python through `ruff check
--fix`, `ruff format`, active-line counting, and retests. Run the project pytest
suite and applicable `make check`, `make check-docker`, `make windows-test`, and demo
checks using Makefile/CI environments. On Linux/macOS use
`make BIN=.venv/bin <target>`. Run `make docs-check`; update SRS/runtime guides and
the ledger when implementation completes, recording actual results and remaining
gaps. Implementation and qualification evidence are recorded in the linked ledger.
