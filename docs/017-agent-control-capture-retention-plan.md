# Screenshot retention implementation plan

Status: implemented (R1–R5). See the [screenshot retention runtime guide](019-agent-control-capture-retention-runtime.md) for configuration, cleanup behavior, and validation.

Allow a workspace owner to configure how many screenshots to retain, how much storage they may consume, and how long to retain them. Delete the oldest eligible captures first. Keep screenshot history usable when an image has expired or is missing.

This extends [computer observation and retained outputs](018-agent-control-backend-features-plan.md) and the [backend runtime](016-agent-control-backend-runtime.md). Apply the same policy to captures stored by Agent Control from Docker, Azure compute, and Windows/UFO computers.

## User experience and scope

Add **Workspace settings → Storage → Screenshot retention**. The policy covers all bots and both browser/desktop surfaces in the selected workspace. Label this scope explicitly: a busy bot can consume the workspace's screenshot allowance. Per-bot overrides are deferred so the first release has one predictable budget.

Offer three independently enabled limits; require at least one:

| Setting | User input | Effect |
| --- | --- | --- |
| Keep latest screenshots | Positive whole number, such as 1,000 | Retain at most that many captures across the workspace; remove older captures as new ones arrive. |
| Limit screenshot storage | Maximum size, reserve percentage, cleanup target percentage | Start cleanup at the configured threshold and reclaim older captures down to the target. |
| Delete screenshots older than | **1 day**, **1 week**, or a positive custom number of hours/days | Expire captures continuously by age. One day means 24 hours; one week means 168 hours. |

When multiple limits are enabled, all apply. For example, keep the latest 1,000 screenshots for at most seven days within the configured storage budget. A disabled field is stored as `null`, not zero or an ambiguous unlimited value.

Show the saved policy, retained count, screenshot bytes, pending deletion bytes, last cleanup time, and cleanup errors. Show shared workspace storage usage separately. Keep Save and Cancel visible in the existing responsive settings layout; include inline validation and a concise preview of the effective thresholds.

Saving a stricter policy applies it to existing captures as well as new captures. Before Save, display an estimated count/size to be removed and the text **Saving applies these limits to existing screenshots. Deleted screenshots cannot be restored.** Save commits the configuration and schedules cleanup; it does not block the page until every file is deleted. Show **Cleanup pending**, then the result. No second confirmation dialog is required.

Existing workspaces default to the current seven-day age limit, with count and screenshot-specific disk limits disabled. Preserve the existing shared workspace storage ceiling during migration. New workspaces initially use the same defaults.

Only workspace owners can change this policy or preview deletion impact. Operators/viewers cannot change retention. Existing bot, Windows desktop, and share permissions continue to govern image access; storage configuration grants no additional access to images or private capture metadata. Aggregate storage statistics must not expose window titles, URLs, or private bot details.

Scope is the retained screenshot store beside `CONTROL_DB`. This policy does not delete chat messages, action outcomes, uploaded files, retained artifacts, bot working files, model-provider data, backups, or independent UFO/debug logs. Copies downloaded by a user are outside its control. Inventory any additional durable image copies during implementation and document them; do not claim that pruning this store deletes every copy of an image.

## Existing behavior and gaps

| Area | Current implementation | Change needed |
| --- | --- | --- |
| Capture persistence | `EventStore.record_capture()` in `event_store.py` writes PNG files under `CONTROL_DB.with_suffix(".blobs")`, inserts `capture_records`, and emits `capture.available`. Each PNG is limited to 4 MiB. | Central retention policy and admission accounting for every producer. |
| Existing limits | `EventStore` defaults to `capture_days=7` and `blob_limit=256 * 1024 * 1024`; captures and `file_blobs` share that workspace ceiling. A capture over the ceiling is silently skipped. | Configurable limits, oldest-first reclamation, and an explicit storage failure result. |
| Cleanup | `EventStore.prune()` removes old rows, then scans direct `capture_*` files and deletes files absent from its retained-ID snapshot. Startup and the runtime sweep invoke it. | Bounded cleanup with durable deletion state; prevent a scan from deleting a capture written after the snapshot. |
| History | `Computers.history()` queries rows; snapshots and replay still contain old `capture.available` events. | A current availability projection independent of event retention. |
| Capture downloads | Normal and shared routes check file existence and return 404 for unavailable images. File serving can still race with deletion after this check. | Coordinate reads/deletion and handle missing files without a server error. |
| Frontend | `v2.ts` reconstructs screenshots from events and retains 30 in memory. `LiveScreen`, overview tiles, and shared views render direct image URLs without a common error fallback. | Prevent replay from restoring expired thumbnails; gracefully handle deletion while a view is open. |

The frontend's 30-image memory limit is not server retention. `EVENT_RETENTION_DAYS` remains independent: keeping messages/events longer than screenshot bytes is supported.

## Retention rules

### Count

Count available stored captures, across all bots/sessions/surfaces in the workspace. Include the incoming capture when determining whether the limit would be exceeded. Keep the newest accepted capture and remove the oldest until the available count is at most `max_count`.

Assign a monotonic storage sequence for deterministic oldest-first order, including simultaneous captures. Use the same ordering for disk eviction. Existing captures receive an order based on `(created_at, id)` during migration; never use filesystem modification times or provider-reported timestamps to choose eviction order.

### Disk quota and reserve

Store all sizes as integer bytes. The UI offers explicit MiB/GiB units: **1 GiB = 1,073,741,824 bytes**. If GB is offered later, distinguish its decimal conversion. Account for PNG file lengths, not base64 transport size; this is a logical screenshot budget, not a guarantee that a percentage of the host's entire disk stays free.

Let:

- `Q` = maximum screenshot bytes.
- `R` = reserve percentage, default **25**.
- `H = floor(Q × (100 − R) / 100)` = cleanup trigger.
- `L = floor(Q × cleanup_target_percent / 100)` = cleanup target, default **50%** of `Q`.

When projected usage, including the incoming capture, reaches or exceeds `H`, remove the oldest captures until projected usage is at or below `L`. At rest, cleanup uses actual usage. Delete whole files, so final usage can be below the target. The target is a percentage of the maximum quota, not a percentage of the amount present at cleanup time.

| Example: maximum 1 GiB, reserve 25%, target 50% | Bytes | Display |
| --- | --- | --- |
| Maximum | 1,073,741,824 | 1 GiB |
| Start cleanup at | 805,306,368 | 768 MiB / 0.75 GiB |
| Finish cleanup at or below | 536,870,912 | 512 MiB / 0.50 GiB |

Validate `0 < cleanup_target_percent < 100 − reserve_percent < 100`. Require a quota/target that can accommodate the maximum accepted 4 MiB PNG. Reject invalid policy values rather than silently rounding percentages or retaining no images. Continue enforcing the existing per-image size/dimension checks.

Count available bytes, reserved in-flight writes, and files awaiting successful deletion against disk capacity. Marking a row unavailable does not reclaim disk space. If locked files, filesystem errors, or insufficient space prevent reclamation, report that condition and do not over-admit writes. An oversized/unstorable capture produces an explicit **Screenshot not retained** result; it does not erase the task's result or claim the computer action failed.

### Age / rotating retention

Use server-assigned UTC `created_at` as the retention clock. A capture expires when `created_at <= now − max_age_seconds`. This is a rolling window, not a daily/weekly midnight reset, and reading a screenshot does not extend its lifetime.

Apply the cutoff on reads as soon as it is reached. Reclaim bytes on a dedicated cleanup tick, proposed every 60 seconds, and during startup, policy changes, and capture admission. A normal cleanup tick should reclaim expired bytes within one interval; pending deletion failures remain visible and retryable.

### Combined limits and shared file storage

First expire by age, then enforce count, then evaluate disk thresholds on the remaining captures plus any incoming capture. Preserve the newest accepted capture when count/disk eviction runs. Age expiry can remove the last capture of an inactive bot; there is no indefinite latest-image exemption.

Retain the existing shared workspace blob ceiling as a separate deployment limit and make it configurable through a proposed `WORKSPACE_BLOB_LIMIT_BYTES` setting wired from `app.py` through `Runtime` to `EventStore`. Keep its default at 256 MiB for upgrade compatibility. Advertise this ceiling and combined usage to the settings UI.

A screenshot quota cannot exceed that ceiling. To configure the 1 GiB example, the deployment must first allow at least 1 GiB of shared storage, preferably more for retained files (for example, 2 GiB). Reject an unsupported quota with an explanation showing the actual ceiling. Never display an effective 1 GiB allowance while silently enforcing the old 256 MiB maximum.

The shared ceiling may require earlier screenshot eviction even when screenshot-specific disk retention is disabled. Under storage pressure, capture admission may evict old captures; it must not delete artifacts/uploads to make room. File-blob admission retains its current quota failure behavior and must count pending capture bytes. If retained files alone exhaust the shared allowance, return a clear capture-storage error. Explain this earlier-eviction behavior next to the screenshot policy.

## Backend design

### Persistence

Add the next available migration, proposed `017_capture_retention.sql` (renumber if another migration lands first):

- `workspace_capture_retention`: `workspace_id`, `revision`, nullable `max_count`, nullable `max_bytes`, `reserve_percent`, `cleanup_target_percent`, nullable `max_age_seconds`, `updated_by`, `updated_at`. Seed existing workspaces with seven-day retention.
- Extend capture storage metadata with workspace identity, storage sequence, availability state (`available`, `pending_delete`, `removed`), removal reason (`age`, `count`, `quota`, `workspace_quota`, `missing`), and removal time. Preserve the existing capture IDs and URLs. Index workspace/order and workspace/age for bounded candidate selection.
- Track reserved bytes and deletion work durably, including enough workspace/blob identity to finish reclaiming files after bot deletion or a restart. Coordinate catalog cascade deletion with this ledger; a deleted bot must not strand quota charges or files.
- Persist a per-bot `captures_revision` and bounded cleanup statistics. Removed-capture tombstones need only survive the related event retention/replay window; compact them afterward. A long-lived share URL must still return 404 after its tombstone is compacted.

Use an isolated `capture_retention.py` service for policy validation, candidate selection, reservations, marking unavailable, deletion retries, and reconciliation. Route all existing capture writers through it using `EventStore.record_capture()` as the common entry point. Reuse the existing single-control-process deployment lock and serialize workspace admission/cleanup; distributed workers are outside this release.

### Write and cleanup sequence

1. Validate the PNG and resolve workspace/policy under the admission lock. Account for the proposed capture before accepting another writer.
2. Select an ordered, bounded eviction batch. Commit unavailability, reasons, revision changes, and pending deletion work transactionally. An unavailable capture must disappear from usable history before its bytes are removed.
3. Delete only the selected server-generated files within the store's fixed capture directory. Do not recursively scan or remove arbitrary working files, symlinks/reparse targets outside that directory, or the artifacts subdirectory. Perform filesystem I/O outside long SQLite transactions; preserve serialization of budget reservations.
4. Release byte charges only after successful unlink or confirmed absence. Retry Windows sharing violations with bounded backoff and expose persistent errors. Additional batches continue until limits are satisfied; yield between batches so chat and control stay responsive.
5. Once space is available, reserve/write the incoming PNG to a temporary file, atomically rename it, and commit its row plus `capture.available`. Release its reservation on any failure. Never emit an available event for a failed write. Capture storage failures must have typed results handled by background capture, manual capture, adapters, and control callers.
6. On startup, reconcile rows, unfinished writes, pending deletions, and orphan files before capture admission. Remove abandoned temporary/orphan files only under the startup process lock, or with an explicit grace period and writer coordination during runtime. Never use an old retained-ID snapshot as permission to delete newly created files.

Keep automatic enforcement independent of browser sessions and computer idle/hibernate status. Split capture cleanup from the existing event/artifact age pruning so a legacy seven-day capture branch cannot override a saved longer policy. Bound database batch size and per-tick work; expose cleanup backlog instead of blocking the event loop for a large policy change.

Do not pin all screenshots for an active run or a share grant. Coordinate brief image-read leases with deletion and handle disappearance before opening a response as 404. Human input still requires the latest valid surface/viewport capture. If that capture expires, invalidate the view's input target, release pressed inputs, and require a fresh valid capture before accepting further input. The agent's in-flight image observation remains available in memory; deleting retained history does not replay or retry its action.

### API and events

| Proposed contract | Behavior |
| --- | --- |
| `GET /api/workspaces/{wid}/capture-retention` | Return authorized policy, revision, scope, usage, shared ceiling, calculated thresholds, and cleanup status. |
| `POST /api/workspaces/{wid}/capture-retention/preview` | Owner-only, read-only estimate for a proposed policy; return counts/bytes without private capture metadata. No deletion. |
| `PATCH /api/workspaces/{wid}/capture-retention` | Owner-only compare-and-set update with expected revision; persist and queue cleanup. Return saved policy/status. Invalid input returns 422; stale revision returns 409 and preserves the UI draft. |
| Existing capture history/latest APIs | Only return currently available, unexpired images. Filter missing files and schedule reconciliation. Continue scanning bounded pages when needed so an unavailable first row does not hide a newer valid result. |
| Existing normal/shared image routes | Preserve private/no-store and authorization. Missing, expired, or removed images return 404; deletion races must not become 500 errors. |
| Bot snapshots | Add an authoritative retained capture page and `captures_revision`, built consistently with `snapshot_seq`. This page supplies the latest 30 available images independently of the last 500 events. |
| `captures.changed` bot event | Notify an affected bot of its capture revision and removal reason/count; use bounded removed-ID batches or force a capture-history refetch. Do not put workspace-wide private IDs into a bot's stream. |

Preserve durable event sequence numbers and task history. Do not delete action/message events just because their referenced images expired. A raw old `capture.available` event records a historical fact; it is not authoritative evidence that bytes still exist. Snapshot hydration must replace replay-derived screenshots with the current retained projection. Reconnect, missed invalidation, and event-retention gaps all refetch/reconcile that projection before showing images.

Use cursor pagination ordered by `(storage_sequence, id)` for retained history, with bot/surface/session filters. Preserve existing clients' parameters during transition or advertise an explicit capability, proposed `capture_retention`, before enabling new response handling. Legacy screenshot frames must omit unavailable images and catch file disappearance while reading.

## Frontend history behavior

Add a reusable `CaptureImage` component and availability-aware capture state. Apply it to the main screen, history thumbnails, overview tiles, and shared captures; cover any capture links in activity/history views as well.

- On an authoritative removal or age expiry, remove the thumbnail and drop its image URL from rendered state. Keep related text, timestamps, and action results.
- If the selected screenshot disappears, show **Screenshot no longer available** with **View latest** when another capture exists. Never silently present a different image as the selected historical capture.
- When no captures remain, show **No retained screenshots** with the existing Capture now action when supported. Disable zoom, image download, coordinate input, and cursor overlays while no valid image is displayed.
- Every rendered image must handle load errors, including deletion between a list response and image fetch. Hide failed image elements so the browser's broken-image icon is never shown. Reset errors when the capture ID/URL changes.
- An image error alone cannot distinguish deletion from network/authentication failure. Revalidate availability once: confirmed absence removes the item; temporary failure shows **Screenshot could not be loaded** with Retry. Do not permanently tombstone a capture on a transient network failure, create retry loops, or issue a separate HEAD request for every thumbnail.
- On `captures.changed`, invalidate the affected retained-history queries and reconcile selected/latest IDs and session screenshots. On reconnect, hydrate from the server projection rather than merging expired URLs back into the cache. Scope request results to bot/workspace/revision so late responses cannot resurrect removed captures.
- Keep already open views current through removal events and age deadlines; a screenshot must not remain indefinitely visible merely because its bytes were loaded before cleanup. Clear cached object URLs if the implementation introduces them.
- Keep the 30-image in-memory display bound and provide bounded older-history loading. Distinguish **earlier captures not loaded** from **captures deleted by retention**.

Shared views need the same image fallback and availability refresh while open. A share does not pin a screenshot or extend retention. Existing private Windows history restrictions continue to apply.

## Delivery milestones

| Milestone | Work | Acceptance evidence |
| --- | --- | --- |
| R1 — Policy and migration | Schema, defaults, validation, ownership, revisioned API, shared-ceiling configuration, preview and usage. | Upgrade preserves existing bytes/default age; owner edits persist after restart; invalid/stale/unauthorized updates are rejected. |
| R2 — Retention engine | Count/age/disk selection, projected admission, pending-delete accounting, bounded worker, all producers, startup reconciliation. | Newest captures survive count/disk cleanup; quota example reaches the target; deletion failures never create fictitious free space. |
| R3 — Availability and history | Retained snapshot projection, list/latest/shared routes, invalidation events, read/deletion races and input handling. | Expired references cannot restore images through replay; missing files return 404, and capture expiry cannot enable stale coordinate input. |
| R4 — Settings UI | Workspace Storage panel, optional limits, thresholds, impact preview, Save/status/error handling. | A user can configure count, 1 GiB/25%/50% (with sufficient deployment ceiling), one-day/week retention, and combinations at desktop/mobile widths. |
| R5 — Image fallback and release | Shared image component, selection/reconnect handling, regression coverage, documentation and capability rollout. | No broken-image UI across screen/history/overview/share views; selected-image deletion and temporary network failure behave distinctly. |

Implement R1 → R2 → R3, then finish R4/R5. Ship the new destructive policy controls only with availability handling and image fallbacks ready. Existing cleanup already removes screenshots, so the image fallback can ship earlier as an independent fix.

Primary code locations: backend `event_store.py`, new `capture_retention.py`, `computer.py`, `control.py`, `transport.py`, `workspaces.py`, `runtime.py`, `app.py`, `blob_store.py`, and the next migration; frontend `WorkspaceCenter.tsx`, new retention settings and shared image components, `LiveScreen.tsx`, `MultiBotGrid.tsx`, shared views, `session/v2.ts`, and the session store/types.

## Validation and release checks

Use temporary databases/blob directories and injected clocks. Large quota arithmetic tests use scaled fixture sizes or metadata accounting; no test needs to fill a developer's disk with a gigabyte of images.

1. **Count:** N+1 captures retains exactly the newest N; N=1, simultaneous writers, cross-bot ordering, and workspace isolation behave deterministically.
2. **Disk:** test just below, exactly at, and above the trigger; include the incoming PNG; prove 1 GiB/25%/50% arithmetic, whole-file overshoot below the target, and no cleanup merely because usage is above 50% but below 75%.
3. **Age:** test one day/one week, exact cutoff, UTC/DST behavior, startup after downtime, and expiry of the final screenshot. Provider timestamps and file mtime do not change expiry.
4. **Combined/storage pressure:** enforce all enabled limits; artifacts consume shared allowance without being deleted; pending files remain charged; unsupported quotas fail clearly; changing or disabling one limit leaves the others effective.
5. **Failures/recovery:** inject unlink/write/rename/database failures, locked Windows files, deleted files, stale orphan scans, concurrent reservations, bot deletion, and restart after each persistence boundary. Verify bounded retries and accurate actual disk accounting.
6. **History/access:** snapshots, event replay, missed invalidations, pagination, shared links, membership revocation, and direct URLs return current availability without losing messages/actions or exposing another workspace's captures. An older valid capture remains discoverable when newer rows are missing.
7. **Live control:** deletion concurrent with image serving/click input yields a controlled outcome; expired targets cannot drive stale input; new captures restore the normal control flow without retrying a completed action.
8. **Frontend:** exercise owner save/reopen, stale drafts, workspace switching, selected-image expiry, all-images expiry, deletion after list fetch, offline retry, and reconnect. Browser checks cover desktop/mobile settings and each capture display surface without broken images.

Add focused backend `test_capture_retention.py`, extend existing runtime/workspace/control coverage, add frontend retention/image/reducer tests, and a browser retention scenario. Run affected tests and the production frontend build. Exercise the common capture path with Docker, Azure, and Windows provider fixtures; report any unavailable live-provider smoke checks separately.

Update `.env.example` and the backend runtime guide with deployment ceiling configuration, exact quota units, 75%/50% cleanup behavior, policy scope, failure states, and independent event/artifact retention. Rollback can restore old code/configuration only after schema compatibility review; it cannot restore deleted screenshot bytes. Do not run cleanup against real workspace data as part of implementing or testing this plan.
