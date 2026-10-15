# Screenshot retention

Workspace owners configure retained screenshots in **Workspace settings → Storage**. Enable a count limit, storage limit, age limit, or a combination. The policy applies across all bots and browser/desktop surfaces in that workspace, including captures from Docker, Azure, and Windows/UFO computers stored by Agent Control.

Rebuild/reload the frontend and restart `agentbot-control` after upgrading. Migration `017_capture_retention.sql` preserves existing capture IDs/files, backfills storage order, and installs a seven-day policy for existing and new workspaces. Count and screenshot-specific storage limits start disabled. Updating the application does not enable a smaller custom limit automatically.

## Configure limits

| Setting | Behavior |
| --- | --- |
| Keep latest screenshots | Keep the newest N captures across the workspace. N must be a positive integer. |
| Limit screenshot storage | Set a maximum in GiB or MiB, a reserve percentage, and a cleanup target. Defaults are 25% reserve and 50% target. |
| Delete screenshots older than | Choose 1 day, 1 week, or custom hours. Age is a rolling UTC duration from server capture time, independent of reads, timezone, and calendar midnight. |

At least one limit is required. Enabled limits work together, in age/count/storage order. The Save preview estimates how many existing screenshots will be removed. Saving applies the new policy to existing and future captures and starts background cleanup; the settings page reports pending cleanup, deletion errors, actual stored bytes, and pending deletion bytes. A stale settings revision preserves your draft and asks you to reload.

For **1 GiB maximum, 25% reserve, 50% target**:

- Cleanup triggers at **768 MiB** (75% of the maximum), including the incoming screenshot.
- Oldest screenshots are removed until projected usage is **512 MiB or less**.
- Cleanup does not run merely because usage is above 512 MiB while it remains below 768 MiB.
- Whole-file deletion can take usage below the target. Each accepted PNG remains limited to 4 MiB; the configured target must have room for one maximum-size PNG.

The quota measures PNG file bytes, not base64 payloads or total filesystem capacity. Reserve is headroom within the screenshot budget; it does not reserve physical host disk space.

## Shared workspace storage ceiling

`WORKSPACE_BLOB_LIMIT_BYTES` sets the combined ceiling for screenshots and retained artifacts/uploads. Its default remains **268435456** (256 MiB). To use a 1 GiB screenshot quota while leaving space for retained files, configure, for example:

```dotenv
WORKSPACE_BLOB_LIMIT_BYTES=2147483648
```

Restart the backend after changing this deployment setting. Then enable **Limit screenshot storage**, enter **1 GiB**, keep **Reserve 25%** and **Clean down to 50%**, and Save. The UI displays the server's actual shared ceiling and rejects screenshot quotas above it.

Retained files can cause earlier screenshot eviction when the shared ceiling is reached. Screenshot cleanup never deletes artifacts, uploads, working files, or chat messages. If files alone exhaust the shared ceiling, new captures cannot be retained. Automatic capture reports `capture.skipped`; manual Capture now returns a storage error. A failed screenshot write does not turn a completed computer action into a failed action or retry it.

## Cleanup and recovery

Captures have monotonic storage order, independent of filesystem mtime. Writes reserve their budget before writing a temporary PNG and atomically renaming it. Capture publication and the available event commit together.

The deletion ledger marks images unavailable before deleting their files. Locked Windows files and other unlink failures remain charged against the quota and retry with bounded backoff. Bytes are released only after successful deletion or confirmed absence. Cleanup operates in batches of 100, with a normal 60-second tick and faster follow-up passes while work remains. Policy saves wake the worker immediately. New capture admission also enforces the limits; if a large cleanup has not yet freed enough capacity, the new screenshot is explicitly skipped until cleanup catches up.

On restart, recovery reconciles pending writes/deletions, missing files, and orphan capture files under the deployment process lock. Deletion work survives bot removal. Only server-generated direct capture files in the fixed blob directory are eligible; the artifacts directory and bot working directories are separate. Shutdown drains cleanup before releasing the process lock. This follows the existing single-control-process SQLite deployment model.

Age-expired captures become unreadable at their cutoff even before the next deletion tick. No active bot or share grants an indefinite retention exemption. Physical deletion can lag while files are locked or a large backlog is being processed; the UI exposes that backlog.

## History and access

Bot snapshots include an authoritative current capture page independently of old `capture.available` events. Removal events invalidate capture state; reconnect reconciles with the current projection. Existing task messages, action results, and event ordering remain intact.

The frontend keeps the latest 30 captures in session state and can load older history in bounded pages. Main images, thumbnails, overview images, and shared images all handle load failure. Confirmed missing images disappear from usable history; transient failures show a retry action where appropriate. A selected expired image shows **Screenshot no longer available** and an explicit **View latest** action. Empty retained history shows **No retained screenshots**. Already loaded captures have expiry timers.

Private/no-store image endpoints return 404 for unavailable captures. Shared image streams continue checking the current share grant. Windows desktop privacy and workspace membership checks are unchanged. Human control rejects clicks/keys targeting an expired capture; releasing held input remains possible without a retained image.

`EVENT_RETENTION_DAYS` still controls event history, and retained artifact files keep their existing seven-day expiry. This feature manages the control-plane PNG store. It does not remove user downloads, backups, screenshots deliberately saved as working files/artifacts, independent UFO/debug logs, or model-provider data. Adapter image observations used by an in-flight task are not replayed or cancelled when their retained copy is deleted.

## API and verification

- `GET /api/workspaces/{wid}/capture-retention`: policy, revision, aggregate usage, deployment ceiling, cleanup status, and current role.
- `POST /api/workspaces/{wid}/capture-retention/preview`: owner-only read-only estimate.
- `PATCH /api/workspaces/{wid}/capture-retention`: owner-only revisioned save.
- Existing capture list/latest/image routes enforce current availability. Capture list supports `before_sequence` in addition to the legacy timestamp parameter.
- Snapshots advertise `captures`, `captures_revision`, and the `capture_retention` capability; `captures.changed` carries bounded removed IDs, and `capture.skipped` carries the storage failure reason.

Regression coverage includes migration, newest-first retention, concurrent writers, quota threshold arithmetic, combined limits, UTC age cutoffs, failed writes/deletes, orphan recovery, artifact isolation, bot deletion, pagination, access checks, stale input, replay, and frontend missing-image behavior. Browser checks cover settings at 1600px/390px and a shared image disappearing between listing and loading. Provider-specific live computers are not required by these tests; the common capture pipeline uses fixtures. No live Azure or Windows desktop smoke test is claimed.

See the [implementation plan](017-agent-control-capture-retention-plan.md) and [backend runtime guide](016-agent-control-backend-runtime.md).
