# SRS-006 Backend features

Server-owned behavior beyond the kernel and the computer driver: approvals, Autopilot, collaboration, tools, routines, and capture retention.

## Approvals and policies

| ID | Requirement |
| --- | --- |
| BE-001 | The server MUST be the authority for approvals. Page-local "Always allow" grants MUST NOT be imported or enforced. |
| BE-002 | Each approval MUST store run, generation, action id, argument digest, deadline, revision, status, and decision principal. The server MUST recheck context before accepting a decision and again at dispatch. |
| BE-003 | Creating a policy MUST NOT approve the current request. Policy TTL MUST be 60 seconds to 30 days. The UI SHOULD offer one hour, one day, and seven days. Revocation MUST increment the rule version and MUST stop future matches. An action already executing MUST be allowed to finish. |
| BE-004 | Shell rules MUST match exact command text plus a SHA-256 revision of the complete bounded workspace. Any content, path, or permission change MUST prevent a match. Substring, regex, and category grants MUST NOT be accepted. |
| BE-005 | Workspace revisions used for shell rules MUST be limited to 2000 entries and 64 MiB. A tree that contains a symlink or special file MUST NOT receive a persistent shell rule. Checked agent text writes MUST be at most 64 KiB and MUST reject symlink traversal. |
| BE-006 | File write and edit rules MUST bind the confined path, the exact mutation digest, and the expected prior revision, including `missing`. |
| BE-007 | Browser-open rules MUST bind one canonical http or https origin. Navigation or redirects to another origin MUST be blocked before the target request. Clicks and desktop input MUST still require approval. |
| BE-008 | No matching rule MUST produce an approval request. Automated decisions MUST record policy id and version. `ActionArbiter` MUST be the shared dispatch path for chat, skills, connectors, routines, and handoffs. |
| BE-009 | `CommandResult` MUST record command id, nullable exit code, stdout, stderr, per-stream truncation, timeout or cancellation, and timestamps. Legacy `TOOL_CALL` text MUST NOT establish an execution outcome. An unknown result after interruption MUST stay unknown. |

## Autopilot

| ID | Requirement |
| --- | --- |
| BE-010 | `GET /api/bots/{id}/autopilot` MUST return `enabled`, `revision`, `changed_by`, `changed_at`, and caller-specific `can_manage`. `POST` MUST accept `{request_id, enabled, expected_revision}` and MUST be bot-owner-only. Members MAY read. An operator still needs an execution grant to run. |
| BE-011 | Identical retries MUST return the existing receipt. A stale revision or a reused request id with a different payload MUST return 409. Writing the same value at the current revision MUST NOT increment it. |
| BE-012 | The setting change, pending decisions, and the command receipt MUST commit together with `bot.autopilot.changed`. Waiters MUST wake after commit. The toggle handler MUST NOT take the instance action lock. |
| BE-013 | Turning Autopilot off MUST cancel authorizations that have not claimed execution. The dispatcher MUST check the setting revision immediately before claim. Disabling and re-enabling MUST NOT revive an old grant. An executing action MAY finish. Stop MUST stay available. |
| BE-014 | Auto-approved actions MUST emit a decision without a false pending notification and MUST retain the enabling owner and setting revision. The UI MUST be able to show "Auto-approved by Autopilot". |
| BE-015 | Autopilot MUST take precedence over a routine's selected approval policy. It MUST approve eligible pending and future requests through the shared dispatcher with no browser connected. Toggling MUST NOT submit or resume work. Reset, hibernate, closure, and restart MUST preserve the setting. Restart MUST interrupt unfinished runs and MUST NOT resubmit them. |
| BE-016 | Autopilot MUST NOT approve a tool that is no longer installed, MUST NOT bypass a human-control pause, and MUST NOT bypass unknown-outcome recovery. The raw gateway MUST ignore the setting. |

## Workspaces, shares, groups, channels

| ID | Requirement |
| --- | --- |
| BE-017 | Roles MUST be `owner`, `operator`, and `viewer`. Existing users MUST keep a personal workspace. Bot moves between workspaces MUST NOT be supported. Owners MUST grant operators credential-backed execution through execution grants. Sharing MUST NOT expose credential secrets. |
| BE-018 | Preferences MUST persist selected workspace, avatar or display label, sidebar order, read cursors, and onboarding, with revision compare-and-set. `POST /api/bots/{id}/read-cursor` MUST advance only that user's cursor and MUST NOT move it backward. |
| BE-019 | Notifications MUST be durable, deduplicated, and paginated. Search MUST use SQLite FTS over bot, message, skill, and routine metadata plus eligible filenames. Arbitrary file contents MUST NOT be indexed. Diagnostics MUST be owner-only. |
| BE-020 | A share MUST name an authenticated recipient, expiry, and either browser or desktop surfaces or retained artifact ids. The URL alone MUST confer no access. Revocation and expiry MUST be checked on every fetch and byte range. Shares MUST NOT grant bot execution. UFO bots MUST NOT be shareable. |
| BE-021 | A group MUST keep its own conversation and member list. A task MUST mention `@group` or a stable `@bot_id`. Limits MUST be 8 targets, 3 hops, a 1-hour deadline, 1 active child, 8 KiB of explicit context, and 5 UTF-8 artifact versions of at most 64 KiB each. Removed members, cancellation, cycles, and expired parent work MUST NOT create child execution. Each bot MUST keep its own computer, approvals, files, and credentials. |
| BE-022 | `CONTROL_WORKSPACE_CHANNELS=0` or `CONTROL_WORKSPACE_FEATURES=0` MUST hide channel capability and disable admission. Disabling a workspace MUST cancel queued channel work and wait, and MUST keep history. |
| BE-023 | Messaging tools MUST be `list_workspace_bots`, `read_channel_thread`, `send_bot_request`, `reply_to_bot`, `wait_for_reply`, `request_computer_work`, and `resolve_channel_thread`. A send MUST return a durable message id immediately. A reply MUST NOT forge another bot's identity. `wait_for_reply` MUST release the active run slot. No reply MUST be invented from a private transcript. |
| BE-024 | Channel limits MUST be 8 KiB message bodies, 16 KiB of explicit context, a 30-minute root deadline, 8 admitted runs, 32 posts, delegation depth 3, 16 pending inbox items per bot, 128 per workspace, 10 posts per bot per minute, and 100 per workspace per minute. Directory pages MUST be at most 20 profiles and 8 KiB. |
| BE-025 | The directory MUST publish ids, names, owner-written purposes, capability labels, enrollment generation, and availability. It MUST NOT publish instructions, prompts, credentials, transcripts, desktop images, or window titles. Removal MUST pass through a Leaving state and then a Removed tombstone. A new enrollment MUST use a new generation. Failed retirement MUST NOT announce removal. |
| BE-026 | Communication-only runs MUST use the configured model and messaging tools without provisioning a sandbox or contacting a Windows companion. A computer task MUST require an already running computer. The channel MUST NOT release human control, close terminals, start cloud resources, or clear Windows recovery. |
| BE-027 | A matching reply or a terminal delivery failure MUST enqueue one continuation. Replies that arrive before wait registration MUST be retained. A new human task, cancellation, or takeover MUST prevent an old wait from resuming. Artifact grants MUST be revision-bound, revocable, and limited to small UTF-8 versions from the same workspace. A filesystem path MUST NOT become a shared mount. Protected files and private Windows artifacts MUST be rejected. |
| BE-028 | There MUST be no automatic broadcast wake-up, self-messaging, or recursive delegation. Internal messaging MUST NOT grant another owner's credentials or Windows desktop. UFO peer proposals MUST be a typed JSON branch handled before native Windows-action parsing. |

## Tool libraries, skills, and the GitHub connector

| ID | Requirement |
| --- | --- |
| BE-029 | `GET /api/tool-libraries?framework=` MUST return the catalog, compatibility, configuration schemas, and manifest digests. `GET /api/bots/{id}/tools` MUST return the saved selection and edit permission. `PATCH /api/bots/{id}` MUST accept `tool_selection` and `expected_tools_revision`. Omitting the selection MUST preserve it. An empty array MUST remove all tools. Conflicts MUST return 409 and MUST NOT save a partial update. |
| BE-030 | A selection entry MUST include `library_id`, `version`, `tool_id`, and `configuration`. The catalog MUST load from the in-repo registry. Selecting a library MUST NOT run `pip`, `npm`, or arbitrary imports. Instructions and messages MUST NOT install tools. |
| BE-031 | Each admitted run MUST pin binding ids, revisions, versions, and implementation digests. Dispatch MUST validate the binding again in the claim transaction. Additions apply on the next task. Removal MUST cancel dependent pending approvals. An executing action MUST settle. Remove-and-add MUST create a new binding that older runs cannot use. |
| BE-032 | The registry MUST reject duplicate ids, unresolved dependencies, cycles, and conflicting framework bindings. A model-supplied resource id MUST NOT expand the installed set. When several bindings share a tool, the SDK MUST see one canonical wrapper. An empty UFO selection MAY be saved and MUST be shown as a warning. Startup MUST seed existing bots once with their legacy framework tools. |
| BE-033 | A skill MUST be recorded only while a human lease is held. Terminal activity MUST become a manual checkpoint and MUST NOT store terminal input. Saved skills MUST be immutable versions. Coordinate steps MUST be marked fragile and MUST stop on URL, viewport, or checkpoint drift. Replay MUST use the action arbiter and MUST require a released lease. Skills MAY be installed on other bots in the same workspace. |
| BE-034 | The connector catalog MUST contain one item: GitHub repository issues, manifest version 1, using a fine-grained PAT for one repository with metadata read and issues read/write. The PAT MUST be vault-encrypted and MUST NOT enter the sandbox or public events. Operations MUST be connect, health, list issues, create issue, rotate, local revoke, and uninstall. Approval MUST bind connection version, repository, operation, and exact arguments. Rotation or revocation MUST block later use of the old version. OAuth, arbitrary MCP, public packages, and billing MUST NOT be offered. |

## Routines

| ID | Requirement |
| --- | --- |
| BE-035 | Definitions MUST be immutable versions. A disabled or superseded definition MUST NOT admit new work. Already admitted jobs MUST remain. Limits MUST be 100 active definitions and 64 claimed or running jobs per workspace. |
| BE-036 | Interval triggers MUST be 60 seconds to 30 days and MUST keep the original phase across missed occurrences. Daily triggers MUST use an IANA timezone and local HH:MM. Spring-forward gaps MUST be skipped. The repeated fall-back hour MUST fire only on its first occurrence. |
| BE-037 | Missed-run policy `skip` MUST drop an occurrence older than 60 seconds. Policy `latest` MUST coalesce to the most recent due occurrence. There MUST NOT be an unbounded backlog. Overlap MUST be one run per bot, with an explicit skip or a queue bounded by a 30–900 second job budget. |
| BE-038 | Webhooks MUST be `POST /api/webhooks/{id}` with HMAC-SHA256 over `timestamp.delivery_id.raw_body`, headers `X-Agent-Timestamp`, `X-Agent-Delivery`, and `X-Agent-Signature`, a 5-minute timestamp window, a 64 KiB body, and a `{data: {...}}` payload. Delivery ids MUST dedupe across definition edits. Secret rotation MUST invalidate the previous secret. Webhook bodies MUST be task data, not policy or tool instructions. |
| BE-039 | Event triggers MUST be single-bot `run.completed` or `artifact.retained`, correlated to the source event. Routine or handoff output MUST NOT trigger another routine. Depth MUST be capped at 1. Group routines MAY use manual, interval, daily, and webhook triggers with explicit mentions, and each child MUST use that bot's approval mode. Group event triggers and group policy selection MUST NOT be exposed. |
| BE-040 | Claims and receipts MUST survive restart. Recovery MUST bind an already admitted run or handoff before another dispatch. With Autopilot off, the absence of an online operator MUST NOT count as approval. Onboarding MUST be able to create a real bot, connect a credential, and run one explicitly submitted task, and MUST record completion or dismissal per user. |

## Capture retention

| ID | Requirement |
| --- | --- |
| BE-041 | `WORKSPACE_BLOB_LIMIT_BYTES` MUST default to 268435456 (256 MiB) and MUST cap screenshots plus retained artifacts and uploads together. A change MUST require a process restart. Screenshot quota MUST NOT exceed that ceiling. |
| BE-042 | A workspace policy MUST support at least one of count, storage, and age. Age is a rolling UTC window from server `created_at`. Storage MUST trigger at `floor(Q × (100 − R) / 100)` bytes and MUST reclaim toward `floor(Q × target_percent / 100)`. The target is a percentage of the quota, not of current usage. Validation MUST require `0 < target_percent < 100 − reserve_percent < 100`, and the target MUST fit one 4 MiB PNG. |
| BE-043 | Cleanup order MUST be age, then count, then storage, oldest first by monotonic storage sequence, not by filesystem mtime. Files MUST be marked unavailable before unlink. Failures MUST stay charged and retry with bounded backoff. Bytes MUST be released only after successful deletion or confirmed absence. Batches MUST be 100. The tick MUST be about 60 seconds, with faster follow-up while work remains. Policy saves MUST wake the worker immediately. |
| BE-044 | Age-expired captures MUST be unreadable at the cutoff even before the next tick. No active bot or share MUST exempt a capture. Cleanup MUST NOT delete artifacts, uploads, working files, or chat messages. A skipped automatic capture MUST emit `capture.skipped`. Manual capture MUST return a storage error. A failed capture write MUST NOT fail or retry the computer action. |
| BE-045 | Writes MUST reserve budget, write a temporary PNG, and atomically rename it. Publication and `capture.available` MUST commit together. Startup under the process lock MUST reconcile pending writes, missing files, and orphan capture files in the fixed blob directory only. Shutdown MUST drain cleanup before releasing the lock. |
| BE-046 | Owners MUST be able to read policy and usage, preview a change, and save with a revision. Invalid policies MUST return 422. A stale revision MUST return 409. The default installed policy MUST be 7 days. Count and storage limits MAY start unset. |

## Traceability

| IDs | Sources |
| --- | --- |
| BE-001–BE-016 | [016](../016-agent-control-backend-runtime.md); [004](../004-agent-control-autopilot-plan.md); blueprint §10.3 |
| BE-017–BE-028 | [016](../016-agent-control-backend-runtime.md); [015](../015-agent-control-workspace-channel-runtime.md); [014](../014-agent-control-workspace-channel-plan.md) |
| BE-029–BE-034 | [013](../013-agent-control-tool-libraries-runtime.md); [012](../012-agent-control-tool-libraries-plan.md) |
| BE-035–BE-040 | [016](../016-agent-control-backend-runtime.md); [018](../018-agent-control-backend-features-plan.md) B10–B11 |
| BE-041–BE-046 | [019](../019-agent-control-capture-retention-runtime.md); [017](../017-agent-control-capture-retention-plan.md) |
