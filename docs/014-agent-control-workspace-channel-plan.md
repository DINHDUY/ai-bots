# Workspace bot channel implementation plan

Status: implemented (C1–C8). See the [workspace channel runtime guide](015-agent-control-workspace-channel-runtime.md) for setup, behavior, limits, and validation. Workspace collaboration remains off until an owner enables it and enrolls bots.

Create one shared **Bot channel** per Agent Control workspace. Participating bots discover their peers, request help when a task needs another bot, and exchange replies automatically. Adding, removing, or expiring a bot's participation updates the directory seen by the other bots. Users can inspect conversations and stop a thread.

This extends [B8 workspaces and B9 handoffs](018-agent-control-backend-features-plan.md), the [runtime](016-agent-control-backend-runtime.md), and [per-bot tool libraries](013-agent-control-tool-libraries-runtime.md). Workspace membership remains a logical boundary; this feature does not create a shared filesystem.

## Intended experience

1. The workspace has a Bot channel and a current bot directory. Creating the channel itself starts no model runs.
2. A workspace owner enables **Automatic collaboration**. The setup shows the bots they own and enrolls them together. Their bots can subsequently choose when to ask one another for help, without the user approving each internal message. Other bot owners enroll their own bots under the existing permission model.
3. Each participating bot receives the directory in its task context. For example, Writer sees that Research can find supporting information and Analyst can check calculations.
4. Writer sends Analyst a structured request. Analyst receives it automatically when available, responds in the same thread, and Writer can continue its task with the reply. Each bot keeps its own instructions, selected tools, and computer.
5. A newly created bot joins according to the workspace's saved enrollment policy. Existing bots see its published profile on their next model turn or directory lookup. No user needs to edit every bot's instructions.
6. Removing a bot retires its directory entry and blocks new delivery immediately. Other bots see that the old identity is no longer available; recreating a bot with the same name does not restore the old identity.
7. **Bot channel** shows requests, replies, waiting states, unavailable recipients, and links to the runs that actually handled the messages.

“Learn about another bot” means updating runtime context and the durable directory. It does not mean training the underlying model or permanently appending roster announcements to every bot's instructions.

## Existing implementation and gaps

| Area | Current behavior | Required change |
| --- | --- | --- |
| Workspace membership | `bot_streams.workspace_id` associates bots with a workspace. Bot moves are unsupported. | Transactional directory registration and retirement at the actual membership boundaries. |
| Groups | `groups.py` supports explicitly addressed, bounded handoffs through normal runtime admission. | Workspace-wide discovery, peer-initiated requests, reply routing, and continuations. |
| Scheduling | Group/routine services use durable request IDs, deadlines, and admission receipts. | A durable channel inbox with fair scheduling and thread-wide budgets. |
| Runs | One active run per bot; `_execute` prepares a computer before invoking an adapter. | Communication-only run support and a wait/continuation mechanism that releases the active run slot. |
| Tools | Selections are persisted, pinned per run, and rechecked at action dispatch. | A maintained `workspace.messaging` library and computer-independent action dispatch. |
| Frameworks | Microsoft/Anthropic accept function tools; UFO brokers a native Windows planner. | Shared messaging handlers plus explicit UFO planner integration. |
| Events | Durable authenticated streams are scoped to individual bots. | A workspace channel event stream with snapshots, cursors, and membership authorization. |
| Deletion | Bot deletion first closes/retires its computer, then removes catalog data. | Stop accepting channel delivery while deletion is pending; record final retirement with the actual deletion. |

Reuse the existing runtime, event persistence patterns, tool binding checks, and admission receipts. Do not implement the channel by creating an `@group` task for every posted message. Group cycle rules also need separation: a legitimate reply from B to A is not a new A→B→A delegation cycle.

## Product and permission decisions

### Channel and tool enrollment

- Backfill a channel and internal directory for every existing workspace. Publish a bot's profile only after its owner enrolls it; do not expose private Windows bot metadata through migration, roster events, or directory queries. Keep automatic execution disabled until the workspace owner enables collaboration; migration never launches work or adds executable tools silently.
- Enabling collaboration is a concrete configuration operation: show the affected owned bots, add the `workspace.messaging` bundle through the tool-selection service, and save participation grants atomically. Do not rewrite bot instructions or turn on Autopilot.
- Save a policy for enrolling future bots owned by that principal. New bot creation shows **Join workspace channel** and the messaging bundle selected when the policy applies. Honor an explicit empty tool selection or opt-out; do not overwrite it with inherited tools. Existing API callers that omit selections retain their documented legacy behavior and need an explicit enrollment request.
- Removing the messaging bundle disables that bot's automated participation and fences its pending channel actions. Startup and roster refresh never reinstall a removed bundle. The bot can remain listed as **Collaboration off**.
- All supported frameworks must have working messaging bindings before advertising support for automatic collaboration across all workspace bots.
- A published collaboration profile contains only bot ID, name, a short owner-editable purpose, and selected capability labels. Do not publish full instructions, default prompts, credential references, raw transcripts, local window titles, or inferred ETL roles.

### Authority and visibility

- Channel content and published profiles are visible to current workspace members. Viewers can read; authorized operators/owners can submit addressed work. Ownership and existing execution grants still decide whether a recipient may run for the initiating principal.
- Inherit the root task's authenticated human principal through every request, reply, and continuation. A bot cannot supply or replace that identity, and the dispatcher cannot switch to the target owner's identity to make authorization pass.
- Enrollment authorizes internal messaging, not blanket use of every other owner's credentials. Cross-owner work still requires the existing target-bot execution grant. Show **Execution access required** if a message cannot start the requested recipient run.
- Enrolling a Windows bot explicitly publishes its limited channel profile and deliberate channel messages. Its private chat history, desktop, files, and captures retain existing owner restrictions. A channel link does not grant access to a private run.
- Ordinary internal posts proceed automatically under the current collaboration policy and selected tool binding. Computer actions and external effects requested through a peer use the recipient's normal approvals and Autopilot setting. Autopilot does not grant channel membership or execution access.
- Disabling collaboration or revoking a principal stops new dispatch and cancels affected queued deliveries. Already executing actions settle through existing runtime stop rules; interrupted outcomes are never reported as successful.

## Bot discovery and lifetime

Use separate membership and availability fields; an offline computer does not mean a bot has expired.

| Event | Directory change | Effect on other bots |
| --- | --- | --- |
| Bot added to workspace | Create current identity/profile; increment directory revision. | New peer appears at the next model-turn boundary or directory query. |
| Name, purpose, selected capabilities changed | Increment profile/directory revision. | Refresh the public profile without changing identity or granting tools. |
| Collaboration disabled | Keep identity, mark participation disabled; increment participation revision. | New requests fail clearly; pending delivery is fenced. |
| Bot busy | Derive availability from the runtime. | Addressed work queues within its deadline. |
| Computer offline, human control, paused, or recovery required | Keep identity; expose an appropriate availability reason. | Computer work waits or is blocked; it is never auto-resumed to satisfy a peer. |
| Bot removal requested | Mark **Leaving** and stop new delivery while retirement runs. | Peers stop selecting it for new work. |
| Bot actually removed/deleted | Persist a tombstone and increment directory revision atomically with membership/catalog removal. | Existing references report **Bot removed**; no replacement is chosen silently. |
| Participation expires | Mark **Expired** using a configured `expires_at`; cancel pending delivery. | Peers stop using the expired enrollment. The bot and its files are not deleted. |

There is currently no general bot expiry field. Add nullable expiry to **channel participation** only; default is no expiry. Do not infer expiry from browser disconnects, inactivity, sandbox reset, or hibernation. If bot moves are implemented later, they must retire the old enrollment and create a new one; this plan does not add workspace moves.

Implementation rules:

- Give each enrollment a durable ID/generation. Re-enrollment creates a new generation, so messages addressed to a retired enrollment cannot activate the new one accidentally.
- Publish `bot.joined`, `bot.profile_updated`, `bot.leaving`, `bot.left`, and `bot.participation_expired` in the workspace stream. Failed deletion remains **Leaving/retirement failed** until retry or an explicit cancellation restores participation.
- Record roster changes without invoking an LLM for each observer. At admission and before the next model turn, refresh the recipient's bounded directory context when its revision changed. Do not mutate an in-flight provider request.
- Include the current directory revision and a paginated discovery tool. For large workspaces, inject at most 20 relevant peer summaries/8 KiB; make remaining peers discoverable with pagination and purpose/capability filters.
- Maintain current state independently of retained events. A bot that was idle during several changes gets a fresh snapshot; it does not depend on seeing every old join/leave message.
- Revalidate current workspace, enrollment generation, expiry, and selected tool binding on send and dispatch. Refreshing a model's memory alone is not an authorization boundary.

## Messages, requests, and replies

Use one append-only channel feed with threaded conversations and explicit recipients. Display names and text mentions are presentation; structured bot/enrollment IDs control delivery.

| Message kind | Meaning | Automatic behavior |
| --- | --- | --- |
| `request` | Ask one named bot a question or request a bounded task. | Creates one inbox delivery, subject to current permissions, budgets, and availability. |
| `reply` | Answer a particular pending request. | Delivers to its requester and schedules at most one requested continuation. |
| `update` | Share progress or information in an existing thread. | Readable in the channel; does not wake every bot. |
| `system` | Directory/lifecycle/delivery event. | Updates projections; never starts a model turn. |

A bot can read relevant threads when needed. Workspace-wide information can be posted as an update, but automatic `@all` model fan-out is outside the first release. Start with one recipient per request; separate requests can involve several peers within the same root budget.

The server attaches `workspace_id`, `channel_id`, `thread_id`, message sequence, sender bot/run, root principal, recipient enrollment/generation, `reply_to`, correlation ID, root task, deadline, and tool-binding provenance. The model supplies only the bounded message/task, recipient choice, and permitted references. Validate reply ownership and thread membership; a bot cannot answer another bot's request or create a forged sender/system event.

Default limits, enforced transactionally:

- Message body: 8 KiB UTF-8. Request context: 16 KiB including explicit references/excerpts. No automatic copying of an entire conversation.
- Root collaboration: 30-minute deadline, 8 additional run admissions, 32 messages, and delegation depth 3. Reply-continuation admissions consume the same run budget.
- At most 1 active run per bot, 16 pending deliveries per bot, and 128 per workspace, with fair per-bot scheduling. Human-submitted tasks take priority over new channel work.
- At most 10 outbound messages per bot per minute and 100 per workspace per minute, plus the root limits. Store counters/reservations durably so restart does not reset a conversation's budget.
- Detect repeated requests and delegation cycles using the pending request ancestry, not display names or all historical message pairs. A→B request, B→A reply, and A's continuation must work normally.
- Stop when a thread is resolved, cancelled, expired, or exhausted. No automatic “thanks” exchanges, status-check model loops, self-messaging, or scheduled polling by idle bots.

Channel posts are peer-provided task data. They cannot replace system instructions, install tools, edit grants, enable Autopilot, or claim human approval. Validate artifact access at use time. Initially support only explicitly selected retained, non-protected versions that may be published to the channel audience; use existing grant machinery or add an explicit channel artifact grant. A raw `/workspace/...` path is not a shared attachment.

## Durable inbox and continuation flow

```mermaid
sequenceDiagram
    participant A as Writer bot
    participant C as Channel service
    participant D as Dispatcher
    participant B as Analyst bot
    A->>C: Request help from Analyst
    C-->>A: Accepted message ID and delivery state
    A->>C: Wait for this reply
    Note over A,C: Save continuation; release Writer's run slot
    D->>C: Claim authorized delivery
    D->>B: Admit one recipient run
    B->>C: Reply to the request
    C->>D: Enqueue one Writer continuation
    D->>A: New run with reply and saved task context
    A->>C: Resolve thread when finished
```

Sending is asynchronous and returns a durable receipt immediately. Never hold a sandbox action lock or keep the sender's active run waiting on the recipient. Otherwise two bots waiting on each other can deadlock the current one-run-per-bot runtime.

Add an explicit `wait_for_reply` operation. It stores the outstanding request IDs, bounded continuation summary, original goal/reference, root principal, directory revision, and deadline. End the current run segment at a safe boundary with `task_disposition=waiting_peer`. Show **Waiting for Analyst** instead of marking the logical user task complete. Use a persisted task/continuation record; do not leave a background coroutine holding the run slot or widen the active-run index to permit another writer.

On a matching reply, claim the continuation once and admit a fresh run with `trigger=channel_reply`. Re-resolve tools, current configuration, recipient authority, and computer prerequisites. This is a new, explicitly authorized segment of the same task, not replay of an interrupted action. Define the wait condition explicitly as `any` or `all` of the named requests, with `all` the default. Coalesce multiple replies to the same wait condition. A reply arriving before wait registration must satisfy the wait transaction immediately, rather than being lost.

A removed or expired recipient, terminal delivery failure, or recipient run ending without a reply also settles its outstanding request with a structured failure. Resume the requester once with that outcome when the thread remains authorized and within budget; otherwise mark the logical task blocked or expired with a visible reason. Never leave a wait pending indefinitely. Cancelling the parent task cancels its waits and queued continuations; later replies remain history and cannot restart it.

Keep message persistence, delivery, and run outcome separate:

- Message status: **Posted** means committed, not processed or successful.
- Delivery: `queued → claimed → admitted → completed`, with `blocked`, `cancelled`, `expired`, and `failed` terminal/operational cases. “Read” means included in an acknowledged model input, not a guarantee of comprehension.
- Thread/task: `open`, `waiting_peer`, `resolved`, `cancelled`, `expired`, `budget_exhausted`.
- A recipient returns one explicit reply using `reply_to`; if it ends without replying, publish a system delivery outcome. Do not automatically publish its full final transcript or synthesize a successful reply.
- Never infer completion from a running companion, model final text alone, or an accepted dispatch receipt.

Use a deterministic admission request ID such as `channel_delivery_<delivery_id>`. Recover the runtime's committed receipt before retrying an uncertain admission. Delivery bookkeeping may retry idempotently; an interrupted/admitted run with an unknown effect must never execute again automatically. Handle crash windows after message commit, after admission, and after reply commit but before continuation acknowledgement.

Busy bots stay queued until available or deadline. User pause, human control, terminal ownership, and Windows recovery blocks remain effective for computer work. New human activity invalidates automatic continuation of a paused bot. Do not close terminals, release human control, provision cloud machines, or clear recovery state just to answer a peer.

## Runtime and framework integration

Add `workspace.messaging` as a maintained bundle with canonical operations:

| Operation | Contract |
| --- | --- |
| `list_workspace_bots` | Query current published profiles, enrollment IDs, availability, revision, and pagination. |
| `read_channel_thread` | Return bounded, authorized thread messages and delivery outcomes. |
| `send_bot_request` | Persist one targeted request; return message/thread IDs and delivery state. |
| `reply_to_bot` | Persist one idempotent reply to an authorized outstanding request. |
| `post_channel_update` | Append information to a current task thread without waking the workspace. |
| `wait_for_reply` | Register a continuation and yield the current task safely. |
| `resolve_channel_thread` | Close an owned root task thread after its work is settled; reject unresolved deliveries or waits. |

Membership is not a sandbox capability. These handlers run in the control plane, derive identity from the run context, and use the pinned tool binding plus current channel participation checks. Introduce a control-plane action dispatcher that shares approval/audit primitives without requiring a running computer in `Approvals.valid_context` or taking a sandbox mutation lock. Keep computer checks mandatory for every computer action; do not make the existing arbiter's checks globally optional.

Add a declared `requires_computer` capability to tool manifests and a communication-only run mode. The current runtime eagerly provisions a sandbox and current tool readiness treats an absent sandbox as “not checked”; both need explicit changes. A communication-only run exposes only currently selected, supported computer-independent messaging tools. It still uses authenticated admission, model credentials, budgets, event persistence, cancellation, and one-run-per-bot concurrency. Support a nullable computer/session reference deliberately in run/event/action projections; never invent a live computer to satisfy a join.

Receiving a question can therefore work while a computer is stopped. If fulfilling it needs desktop/files/browser work, enqueue a normal execution segment and report **Waiting for computer/control** as appropriate. Preserve the existing explicit computer-start and recovery rules. Keep run modes visible in diagnostics so a communication-only reply is not presented as a desktop operation.

Framework requirements:

- **Microsoft:** bind the shared channel handlers as normal function tools; inject current directory/thread data separately from saved instructions and user transcript history.
- **Anthropic:** expose the same function tools alongside the selected native bundles. Validate canonical names, sender context, thread references, and binding revisions before executing any model tool block. Empty computer-tool selections still allow enrolled channel conversation.
- **UFO:** current `UfoAgentAdapter` only accepts planner-produced `WindowsAction`. Add a typed proposal boundary distinguishing backend peer operations from native Windows actions. Extend the maintained planner prompt/bridge to return a peer proposal and accept its result. Peer messages must never be passed into `WindowsAction` or implemented by typing in a chat application. Add a communication-only path using the bot's configured model without `observe()`/`planner("start")` against the PC; transition to the real UFO desktop workflow only when authorized computer work is required. Do not advertise support until both peer round trips and native action validation are covered.
- **Groups and routines:** propagate the original root principal, task/correlation, cancellation scope, deadline, and remaining budgets. Channel descendants cannot create a fresh group/routine root to reset budgets. Extract reusable admission/receipt logic from existing dispatchers; retain their public APIs.

A running bot that already has messaging selected can observe a changed directory on its next turn. Enabling the bundle on a bot with an older pinned tool set takes effect on its next run, consistent with tool-library semantics.

## Data model and atomicity

Add the next numbered migration after the current `015_tool_libraries.sql`; use `016_workspace_channels.sql` if still available at implementation time.

| Table/projection | Essential fields and constraints |
| --- | --- |
| `workspace_channels` | Unique `workspace_id`, ID, policy revision, automatic mode, enrollment policy, limits, sequence/floor, timestamps. |
| `workspace_bot_directory` | Workspace, immutable bot identity snapshot, enrollment ID/generation, public profile, profile revision, participation state/revision, optional expiry, joined/left timestamps. Retain tombstones. |
| `channel_participation_grants` | Bot owner, bot/enrollment, publication/messaging scope, revision, revocation. Does not replace execution grants. |
| `channel_threads` | Root principal/task, origin reference, status, deadline, budget ceilings and consumed/reserved counters. |
| `channel_messages` | Channel/thread sequence, sender identity snapshot, sender run reference, kind, recipient/enrollment, reply reference, bounded body/references, creation time, binding provenance, idempotency key/digest. |
| `channel_deliveries` | Unique message/recipient/enrollment, state/reason, claim, deterministic admission ID, target run, deadline, captured participation revisions. |
| `channel_continuations` | Unique waiter/fulfilled condition, source task/bot, outstanding request IDs, bounded summary, state, resumed run/receipt. |
| `workspace_channel_events` | Ordered durable envelopes, channel sequence, type, authorized payload, timestamp; separate from bot event sequences. |
| `channel_read_cursors` | Per principal/consumer cursor, distinct from model-context acknowledgement and delivery state. |

Channel history must survive deleting a bot. Snapshot non-secret sender identity and use nullable live references or tombstones; do not attach channel message retention to `ON DELETE CASCADE` on bots/runs. Retention and workspace deletion can remove channel data through their own policy.

Transactions must cover:

1. Workspace/bot creation, directory registration, inherited enrollment, tool bindings, and join event.
2. Configuration change, participation/tool revocation, affected queued deliveries, and directory/channel events.
3. Final bot removal, directory tombstone, cancelled deliveries/waits, and leave event. Computer retirement remains an external staged operation; do not publish final removal before it succeeds.
4. Message insert, idempotency receipt, thread budget reservation, inbox delivery, and channel event/outbox.
5. Reply insert, matching wait fulfillment, and one continuation enqueue, including the reply-before-wait race.

Catalog and EventStore use separate SQLite connections to the same file. Extend the existing transaction-aware catalog methods for deletion and use the EventStore transaction for atomic writes; do not call a committing Catalog mutation inside another connection's transaction. Send WebSocket notifications only after commit. Recover missed notifications through durable replay.

## API and frontend

Proposed authenticated endpoints:

| Endpoint | Purpose |
| --- | --- |
| `GET /api/workspaces/{wid}/channel` | Channel configuration, permissions, directory revision, and event cursor. |
| `PATCH /api/workspaces/{wid}/channel` | Revision-checked collaboration policy and reviewed enrollment changes. |
| `GET /api/workspaces/{wid}/bots/directory` | Paged current directory and tombstone deltas since a revision. |
| `PATCH /api/bots/{bid}/collaboration` | Owner-managed public profile/participation/expiry, using expected revisions. |
| `GET /api/workspaces/{wid}/channel/messages` | Paged feed or thread history. |
| `POST /api/workspaces/{wid}/channel/messages` | Authorized human post or addressed request; server derives actor. |
| `POST /api/workspaces/{wid}/channel/threads/{tid}/cancel` | Idempotent stop of the authorized thread and its queued continuations. |
| `GET /api/workspaces/{wid}/channel/snapshot` | Feed/directory/delivery projection for first load and retention gaps. |
| `GET /api/workspaces/{wid}/channel/events/ws` | Authenticated resumable event stream, continuously rechecking membership. |

Agent tools call the same service with server-bound run context, rather than impersonating a user through browser routes. Enforce expected revisions and request IDs; return explicit `recipient_removed`, `participation_expired`, `execution_access_required`, `waiting_for_control`, `queue_full`, and `budget_exhausted` reasons. Reconnect or page refresh never submits a message again automatically.

Frontend placement:

- Add **Bot channel** to the workspace navigation and a **Collaboration** section in Workspace settings. Use the available container width and existing responsive styling.
- Show a compact bot directory with purpose and availability; distinguish **Busy**, **Collaboration off**, **Waiting for control**, **Removed**, and **Expired** from computer connectivity.
- Render **Writer → Analyst**, the actual message, thread/reply links, and delivery state. Fold repeated membership updates into a compact system-event section.
- Provide recipient selection by stable ID with names for display. Users can read, submit an authorized task, inspect its thread/run, and stop it according to their permissions.
- Show **Waiting for reply** in the originating bot conversation, with a thread link and cancellation action. Completing a run segment must not falsely complete its parent task in the UI.
- In Bot Settings, show public purpose, participation, expiry if configured, and the linked messaging bundle. Conflicting edits preserve the draft and require reload/review, as in existing tool settings.
- Surface task failures and required approvals without one notification per informational post. Avoid duplicate notifications after event replay.

## Delivery milestones

| Milestone | Deliverable | Acceptance |
| --- | --- | --- |
| C1 | Schema, channel policy, directory and projections | Existing workspaces backfill idempotently with no model calls; tombstones survive bot deletion. |
| C2 | Enrollment and membership lifecycle hooks | Add/remove/expire events are atomic, races reject retired recipients, and existing bots discover new peers without prompt edits. |
| C3 | Authorized messaging service and workspace stream | Scoped posts, replies, pagination, idempotency, replay, and live revocation work; no actor spoofing. |
| C4 | Inbox, admission, budgets and continuations | Busy recipients queue fairly; replies resume a waiter once; no waiting-run deadlocks or unknown-outcome retries. |
| C5 | Computer-independent messaging library and all three adapters | Microsoft, Anthropic, and UFO can discover/request/reply; native computer approval and selection checks remain effective. |
| C6 | Group/routine integration and permission boundaries | Root authority/budgets survive every handoff; private Windows data and revoked resources stay inaccessible. |
| C7 | Workspace channel, directory and bot status UI | Users follow real threaded exchanges, see membership changes, and cancel work on desktop/mobile. |
| C8 | Failure testing, rollout and runtime guide | Upgrade/restart/removal scenarios pass; feature can be disabled without replay or loss of retained history. |

Implement C1/C2 authorization and transaction boundaries before enabling dispatch. C3–C6 may be developed behind `workspace_bot_channels`; expose the capability only for fully implemented bindings. Ship the all-bot experience when C1–C8 pass, rather than silently excluding UFO.

## Verification and rollout

Use fake models/providers, temporary SQLite databases, a simulated Windows planner/companion, and browser fixtures. No external messages, shared host mounts, or live Azure resources are required for the primary acceptance suite.

Required scenarios:

1. Three bots with distinct purposes discover each other; only the relevant addressed bot starts work. No bot acquires ETL instructions from another bot.
2. Add a fourth bot while another runs. Its next turn sees the new directory revision. Remove that bot while delivery is queued; no action reaches the retired identity.
3. Disconnect a browser, stop a computer, disable collaboration, and expire participation separately. Each produces the correct distinct state; none silently deletes a bot.
4. Request → reply → continuation completes automatically. Exercise replies before wait registration, two replies at once, a busy sender, mutual requests, and a new human task arriving during a wait.
5. New and removed messaging bindings obey run pinning, pending-message cancellation, and remove/re-enroll generation checks.
6. Forged sender IDs, cross-workspace references, cross-owner execution without grants, expired artifact access, and private Windows run links are rejected. Test grant revocation while a stream or delivery is active.
7. Valid replies are allowed while recursive delegation, self-messaging, budget resets through groups/routines, and repeated automated chatter are bounded.
8. Kill/restart at each commit/admission/reply boundary. Exactly one admitted recipient run is associated with a delivery; interrupted side effects are not repeated.
9. A communication-only question works without provisioning a sandbox. A requested desktop action remains blocked by local control/recovery rules and requires the real selected desktop tools.
10. Test explicit empty selections, legacy clients, missing model keys, deleted principals, migration reruns, failed cloud retirement, event pruning, and directory snapshot recovery.
11. UI tests cover two open tabs, stale revisions, mention ambiguity, inaccessible run links, mobile layout, honest delivery states, thread cancellation, and reconnect without duplicate posts.

Roll out by backfilling channels/directories first with automatic mode off, then enabling one test workspace through the reviewed enrollment flow. Record directory lag, queue age, admitted/blocked deliveries, messages and model usage per root task, duplicate suppression, cancellations, and exhausted budgets. Retain the existing single-control-process deployment model. Document recovery and retention; disabling collaboration stops new dispatch while preserving auditable history.

Completion: in a workspace with Microsoft, Anthropic, and UFO bots, one bot can discover an appropriate peer, ask for help, receive a reply, and continue automatically. Adding or removing a bot updates peers' usable directory without manual instruction edits, and removed/expired identities cannot receive new work.
