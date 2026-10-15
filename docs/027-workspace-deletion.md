# Workspace deletion

Open **Workspace settings**, select a custom workspace, and expand **Delete
workspace** at the bottom of the page. The panel starts collapsed. Choose the
**Delete workspace** button inside it. Only its owner can delete it. The system-created
Personal workspace is protected. Review the affected bots, messages, people, routines, and stored
files, then enter the exact workspace name and choose **Delete workspace and
contents**. The operation has no application undo.

The preview lists blockers. Finish or stop active tasks, release human control,
wait for file transfers and claimed automation to settle, and close every shared
or per-bot computer. A hibernated, disconnected, failed, or uncertain computer is
still a blocker. Resolve cloud operations through the existing computer controls.
Rejected deletion leaves content and queued work unchanged. If contents change
after preview, refresh and confirm the updated preview.

## Results and recovery

Catalog deletion is atomic: bots, conversations, channel content, groups,
routines, bot-owned tools/secrets, shares, and grants disappear together. Queued
automation cannot start afterward. The owner returns to Personal; workspace and
bot lists in other tabs reconcile every five seconds. Server permissions apply
immediately to new reads and writes and at the existing stream reconciliation
boundary. An already delivered download cannot be recalled.

Files are removed after commit. **Workspace deleted; file cleanup pending** means
catalog deletion succeeded and the cleanup worker still has recorded files to
remove. **Deletion history** lists cleanup progress. If cleanup needs attention,
resolve the indicated filesystem problem and select **Retry file cleanup**.
Missing files count as removed. Failed attempts and outstanding byte counts remain
recorded; restarting the backend resumes unfinished cleanup.

After a lost response, select **Check deletion status** or **Retry original
deletion**. The browser preserves the original request ID across reloads in that
tab. History also recovers completed requests without this browser state. A retry
with the same ID and command returns the original receipt; changed input returns
409. A second request for the same deleted workspace identifies the first request.

For a server failure, the UI includes the HTTP status and retains the original
request until its outcome can be recovered. Authentication, authorization, missing
route, and validation rejections show the returned error. Plain-text error responses
are handled without hiding their HTTP status behind a JSON parsing error.

Account credentials, users, login sessions, other workspaces, paired Windows
machines, and external Azure resources remain. Inactive Azure inventory stays in
deletion history, where the original owner can inspect and reconcile it. Workspace
deletion makes no provider deletion calls and does not erase files on external
machines. Workspace compute profiles are disabled, enrollment tokens removed, and
machine credentials revoked. Retained inventory confers no permission to start
bots or create computers in the deleted workspace.

Historical import receipts remain valid. Recovering one shows **This imported
workspace was deleted** without recreating it. Start a deliberate new import to
create another workflow. Protected backups follow the separate
[operations runbook](021-foundation-operations.md).

## API and persistence

| Request | Result |
| --- | --- |
| `GET /api/workspaces/{wid}/deletion-preview` | Owner-only counts, blockers, retained inventory, and digest |
| `POST /api/workspaces/{wid}/deletions` | Strict `request_id`, `preview_digest`, `confirm_name`; 202 while files remain, otherwise 200 |
| `GET /api/workspace-deletions?cursor=0` | Owner history, 20 receipts per page and optional next cursor |
| `GET /api/workspace-deletions/{request_id}` | Durable status after membership removal |
| `POST /api/workspace-deletions/{request_id}/retry-cleanup` | Empty JSON body; retry existing cleanup |

Unauthorized preview, deletion, status, and recovery requests return 404. Personal
protection, active work, changed previews, and reused request IDs return 409;
invalid commands or confirmation names return 422. The optional capability
`workspace_deletions` follows the workspace-feature gate; existing receipts remain
readable when new deletion is disabled.

Migration `021_workspace_deletions.sql` adds minimal workspace/bot tombstones,
owner receipts, file cleanup items, and durable transfer markers. SQLite triggers
fence late inserts and workspace moves; parent foreign keys fence dependent work.
One database-worker transaction checks current ownership, preview revisions, and
quiescence before removing content and repairing preferences. Filesystem work runs
outside that transaction on the bounded worker, with cancellation drained before
the deployment lock is released.

Migration `022_workspace_deletion_repair.sql` repairs development databases that
recorded an earlier version of 021 without the lifecycle archive table or transfer
staging columns. Conditional column additions and table creation share one migration
transaction; existing transfer state is preserved. Startup applies 022 once. Editing
an already recorded SQL migration does not update a deployed database, so further
schema changes require a new migration.

The required `workspace_cleanup` worker reports progress through readiness. It
processes at most 50 deletion targets and 50 settled upload staging files per
sweep; failed deletion items retry with bounded backoff. IDs and storage roots are
validated, links rejected, and individual files unlinked without recursive path
deletion. Capture cleanup has one owner after workspace deletion. Pending artifact
IDs are excluded from ordinary startup orphan cleanup.

See the [approved plan](026-workspace-deletion-plan.md),
[table and producer audit](028-workspace-deletion-audit.md), and
[implementation evidence](003-agent-control-implementation-status.md).
