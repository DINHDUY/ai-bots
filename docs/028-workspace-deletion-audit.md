# Workspace deletion persistence and producer audit

Migration scope: `001` through `022`. The table classification is executable:
[test_workspace_deletion_audit.py](../packages/agent-control-backend/tests/test_workspace_deletion_audit.py)
compares it to a fresh migrated database. SQLite-owned and FTS shadow tables are
excluded; FTS content is removed through `search_index`.

| Disposition | Tables |
| --- | --- |
| Removed with bot/run cascades | `actions`, `approval_policies`, `approvals`, `bot_autopilot`, `bot_compute_config`, `macos_compute_config`, `bot_events`, `bot_streams`, `bot_tool_bindings`, `bot_tool_config`, `bots`, `capture_records`, `cloud_compute_config`, `command_receipts`, `compute_management_grants`, `computer_health`, `connections`, `execution_grants`, `file_blobs`, `installations`, `messages`, `notifications`, `run_plans`, `run_tool_bindings`, `runs`, `share_grants`, `skill_versions`, `uploads` |
| Removed explicitly in dependency order | `channel_artifact_grants`, `channel_automation_roots`, `channel_continuations`, `channel_deliveries`, `channel_dispatch_checks`, `channel_enrollment_policies`, `channel_messages`, `channel_read_cursors`, `channel_run_context`, `channel_threads`, `computer_control`, `computer_retention`, `computer_sessions`, `control_leases`, `group_members`, `group_messages`, `groups`, `handoffs`, `recordings`, `routine_jobs`, `routine_versions`, `routines`, `search_index`, `terminals`, `webhook_deliveries`, `windows_bindings`, `macos_bindings`, `workspace_bot_directory`, `workspace_capture_retention`, `workspace_channel_events`, `workspace_channels`, `workspace_computer_settings`, `workspace_members` |
| Removed after physical cleanup; existing removed metadata follows retention | `capture_storage` |
| Active markers block deletion; settled staging cleaned before admission | `workspace_file_writers` |
| Workspace profile disabled; binding enrollment removed; machine credentials revoked | `compute_profiles`, `cloud_enrollments`, `cloud_machine_credentials` |
| Retained external inventory and reconciliation evidence | `cloud_operation_receipts`, `cloud_operation_state`, `cloud_resource_inventory`, `computer_provider_bindings` |
| Retained tombstone, immutable receipts, and cleanup evidence | `workspaces`, `workspace_deleted_bots`, `workspace_deleted_operations`, `workspace_deletions`, `workspace_cleanup_items`, `workspace_computer_receipts`, `workflow_import_receipts` |
| Per-bot lifecycle copied before cascade; workspace lifecycle retained | `lifecycle_operations` |
| Repaired selection, order, folders and read cursors; unrelated values preserved | `user_preferences` |
| Account, pairing, anti-replay identity, deployment or schema state preserved | `auth_limits`, `computer_enrollments`, `credentials`, `paired_computers`, `macos_devices`, `macos_enrollments`, `macos_task_links`, `runtime_settings`, `schema_migrations`, `sessions`, `users` |

Bot-owned installations, skill versions and connector secrets are content, even
when their installed packages are reusable. Installed package distributions remain
outside the catalog. Cloud inventory has historical bot IDs without live bot
foreign keys; tombstoned bot IDs preserve its recovery association. Deletion
receipts hold counts and identity, never instruction or conversation copies.

## Producers and final admission

| Producer | Committed barrier before effects; behavior after deletion |
| --- | --- |
| Manual, v2 and legacy starts; approvals and retries | `runs` and `computer_sessions` admission precedes runtime effects. Active or uncertain work blocks deletion; deleted bot IDs and parent FKs reject late writes. Cached `Runtime.ensure` cannot reinsert the bot. |
| Routines and webhooks | `routine_jobs` claim persists before dispatch. Claimed/running jobs block; queued jobs, definitions and webhooks are removed together. Prefetched dispatch cannot find its routine or admit a run. |
| Group handoffs | Claimed/running handoffs block; accepted but unclaimed handoffs are removed. Target bot and group foreign keys prevent re-admission. |
| Channel delivery and continuation | Delivery admission/run is persisted before execution; admitted work blocks. Queue, continuation, thread and context removal prevents replay or late publication. |
| Shared/per-bot lifecycle, Windows and Azure | Lifecycle/session admission precedes provider effects. Every nonclosed session, active binding or uncertain operation blocks; triggers reject new session/binding admission under deleted identity. External inventory remains recoverable by the original owner. |
| Uploads and artifact snapshots | `workspace_file_writers` persists before I/O. Cancellation drains local threaded writes before settlement; staging remains observable until removed. A pending writer blocks deletion. |
| Capture storage | Reservation and write settlement serialize under the store lock; reserved captures block. Deletion snapshots pending IDs; the workspace cleanup worker takes ownership after commit. |
| Human control, recording and terminals | Lease/computer fences and bot/session foreign keys gate admission. Active/releasing leases and nonclosed sessions block. Released control dependencies are explicitly removed before bot/session cascades. |
| Bot creation, editing, enrollment, sharing, tool configuration | Workspace triggers reject late insertion/moves; deleted bot identities cannot be reused. Parent FKs and current membership prevent attaching content, privileges or configuration to missing bots. |
| Search, file/share reads, sockets and import replay | Search projections and grants are removed atomically; new requests reauthorize. Streams reconcile current access at their existing boundary. Import replay stays historical and UI recovery checks the active workspace list. |

The transaction lock orders writers before or after deletion. A write that wins
first changes the preview or creates a blocker; a write that loses cannot create
content below the tombstone. The local file worker retries recorded targets only;
it never constructs paths from workspace names or imported filenames. Cleanup
completion excludes explicitly retained external resources and audit records.
