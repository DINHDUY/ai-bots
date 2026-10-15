# Agent Control Autopilot implementation plan

Status: implemented. AP1–AP4 are complete; Autopilot remains off by default. See the [runtime guide](016-agent-control-backend-runtime.md#autopilot) and [verification record](003-agent-control-implementation-status.md).

- [x] AP1: migration 012, per-bot state, owner-only revisioned API and durable receipts.
- [x] AP2: pending/future decisions, dispatch fencing, routine policy precedence and legacy streamer compatibility.
- [x] AP3: shared checkbox, headers, ordered synchronization and durable decision attribution.
- [x] AP4: permissions, races, recovery, adapters, skills, connectors, routines, handoffs, real Docker, browser tests and documentation.

Add an **Autopilot** checkbox that automatically approves every agent approval request for the selected bot while enabled. Enabling it also resolves valid requests already waiting for approval. The backend owns this behavior, so it works without an open browser.

## Implemented behavior

The initial scope is **per bot**, matching the selected bot's conversation and computer. The setting is off by default, persisted until changed, and editable by the bot owner. Workspace operators with an execution grant can run a bot using its current mode; workspace members can see the mode. A future workspace-wide switch would be a separate feature.

| Situation | Behavior |
| --- | --- |
| Checked | Automatically approve agent shell, file, browser, desktop, skill, and connector requests through the shared approval service. |
| Already waiting | Approve pending requests that are unexpired and still belong to an active run/current computer generation; wake the waiting runtime immediately. |
| Unchecked | Restore ordinary manual approvals and existing exact approval policies. Invalidate Autopilot authorizations that have not claimed execution. |
| Action already executing | Allow it to finish under the existing execution deadline. Stop remains available to cancel the run. |
| Expired, denied, cancelled, or interrupted request | Keep its terminal decision; enabling Autopilot never revives it. |
| Refresh, another tab, or browser closed | Use the same persisted server setting and synchronize through snapshots/events. |
| Backend restart | Preserve the setting for subsequent runs; unfinished work still follows existing interruption/recovery behavior. |
| Close, reset, or hibernate | Preserve this bot setting. Existing lifecycle commands, human-control pause, and explicit resume semantics still apply. |
| Routine or handoff | Apply the target bot's mode. Each group member has its own setting; the source bot's mode does not propagate. |

Autopilot supplies the approval decision. Current membership, execution grants, credential and connector availability, action argument/context validation, filesystem confinement, human leases, and resource/time limits continue to govern execution. It does not start a task or resume a paused agent merely because the checkbox is checked.

While enabled, Autopilot takes precedence over exact approval policies, including a routine's `allowed_policy_id`. The UI must explicitly state that this includes scheduled and handoff runs. When disabled, the routine's original policy restriction applies again. Update the routine policy-availability check accordingly: an expired selected policy does not block an otherwise authorized Autopilot run, while all non-policy admission checks still apply.

## UI

Use a reusable `AutopilotToggle` in the computer controls and Bot settings, backed by one server state. The computer placement uses the wrapping control area introduced by the layout fix. It must also be accessible in Bot settings before a computer exists.

- Label: **Autopilot**.
- Helper text: **Automatically approve all requests for this bot, including scheduled runs and handoffs. Applies immediately to pending requests.**
- Enabled indicator in the bot/workspace header: **Autopilot on**.
- Activity/approval decision label: **Auto-approved by Autopilot**, with the enabling owner and setting revision available in details.
- Owners can check/uncheck directly; the explicit checkbox and helper text are the opt-in. No additional confirmation dialog is required.
- During submission, disable the checkbox and show saving state. Display the checked value only after server acknowledgement; on error keep the last confirmed value and show an inline error.
- Operators/viewers see the current value with a read-only explanation. Chat and settings keep a disabled control with a backend-update explanation when the running server does not advertise the capability; the computer panel hides unsupported controls.
- Use a native checkbox with an associated label/helper description, `width: auto`, keyboard support, and a suitable touch target. Keep text and controls readable in the 320px sidebar and mobile view.

Approval-required cards should disappear from the pending list when resolved. An automatically approved action still progresses through accepted, executing, and completed/failed states; approval alone must not display success.

## AP1 — Persist and expose the setting

Add `migrations/012_autopilot.sql` using the next available migration number at implementation time.

| Storage | Fields |
| --- | --- |
| `bot_autopilot` | `bot_id` primary key referencing the bot with cascade delete; `enabled`; monotonic `revision`; `changed_by`; `changed_at`. |
| `approvals` additions | `decision_source` (`manual`, `policy`, `autopilot`, `observation`, or null while undecided); nullable `autopilot_revision`. Use existing `decided_by` for the enabling owner. |

Existing/new bots without a setting record read as `{enabled: false, revision: 0}`. The first actual change creates revision 1. Existing policy/observation decisions can be backfilled from their stored attribution; pending requests remain undecided. Keep settings in the runtime database, independent of user display preferences and browser storage.

Add a focused `agentbot_control/autopilot.py` service and routes:

| Endpoint | Contract |
| --- | --- |
| `GET /api/bots/{bot_id}/autopilot` | Current enabled state, revision, attribution, and caller-specific `can_manage`. Requires current read access. |
| `POST /api/bots/{bot_id}/autopilot` | `{request_id, enabled, expected_revision}`. Requires explicit bot-owner authorization and the existing origin check. Returns acknowledged state and IDs of approvals resolved/invalidated by this change. |

Use the existing command-receipt mechanism. Bind the request fingerprint to the operation, bot, principal, desired value, and expected revision. Identical retries return the original receipt. Reusing a request ID for a different payload or updating a stale revision returns 409; fetch the latest state before another explicit change. A same-value request with the current revision is a no-op and does not invalidate existing authorizations.

The update is valid during an active run or while awaiting approval. It has a dedicated endpoint independent of ordinary bot configuration updates, which may reject changes while busy. `request_bot()` and the transaction both enforce bot-owner authorization for Autopilot writes.

In one SQLite transaction: check current authorization/revision, update the setting, emit `bot.autopilot.changed`, resolve eligible pending requests or invalidate undispatched Autopilot grants, and save the command receipt. Perform runtime wakeups only after commit.

Expose `autopilot` in capabilities and include the current bot setting in snapshots. The feature belongs to the authenticated approval runtime; raw-gateway sessions do not inherit a bot's setting. No sandbox-image change is expected.

## AP2 — Integrate with approval and dispatch

Primary files: `approvals.py`, `runtime.py`, `event_store.py`, `routines.py`, and `groups.py`.

### New requests

Extend `Approvals.register()` to read the current setting inside its existing transaction. After validating the active run/computer:

1. Preserve system-observation decisions for operations that already require no approval.
2. For approval-requiring operations, if Autopilot is enabled, resolve the request as approved with `decision_source=autopilot`, its setting revision, and the enabling owner's identity.
3. Otherwise evaluate the permitted exact policy and then fall back to the normal pending request.

Record the action, approval, and `approval.resolved` event even when the decision is immediate. Do not emit a transient `approval.required` notification for a request that never waits. Preserve argument digests, sealed arguments, generation, run/action correlation, and the structured result pipeline. Autopilot approval must work even when `scope_for()` cannot produce a reusable exact policy, since it covers every approval request.

### Requests already waiting

On enable, use compare-and-set transitions on still-pending rows after checking expiry and current run/generation. Resolve them with the same attribution as newly registered requests, then call the affected streamers' `resolve()` methods after the transaction commits. Their existing waiters must resume without requiring a new user message.

`ActionArbiter` holds its instance lock while waiting for approval. The toggle handler must not acquire that lock or wait for the blocked action; use the SQLite decision transaction and post-commit wakeup. Live action context is rechecked by the arbiter immediately before execution.

Update `RunStreamer.begin_approval()`/`wait_for_approval()` compatibility handling as well: today it persists a request but ignores the returned approval status. Immediately resolved database decisions must settle its future. Both real Microsoft and Claude adapters continue to use the shared arbiter; do not implement Autopilot as an adapter-specific shortcut or a frontend loop that clicks Allow.

### Disable and races

Extend `Approvals.claim()` to verify the current setting is enabled and its revision matches an Autopilot decision before changing the action from authorized to executing. This check shares the same transaction as `action.started`.

On disable, cancel Autopilot-approved actions that are still authorized and have not claimed execution. Emit their invalidation with the reason **Autopilot disabled before execution**. Return the ordinary cancelled action result to the adapter; a fresh request then uses normal approvals/policies. Preserve the original approval event in history. Already manual/policy-approved actions retain their own authorization.

This gives toggle-versus-dispatch a defined outcome: a claimed action can finish; an unclaimed Autopilot action cannot execute using a revoked setting revision. Turning the feature back on creates a new revision and cannot revive an old decision. Manual denial, timeout, Stop, and takeover races must also have one winning durable transition.

Do not reset existing action/run deadlines or repeat any completed/unknown external side effect when toggling the option.

### All execution entry points

Exercise direct chat, installed skill replay, GitHub invocation from both adapters and its explicit endpoint, routine jobs, and group handoffs. Let every path consult the same per-bot setting at approval time. Verify routine policy filtering cannot accidentally suppress Autopilot, and disabling it restores `allowed_policy_id` behavior. Continue to recheck the executing principal's access before dispatch.

## AP3 — Synchronize presentation and history

Primary frontend files: new `features/bots/AutopilotToggle.tsx`; `BotSettings.tsx`, `BotHeader.tsx`, `ComputerControls.tsx`, `WorkspaceHeader.tsx`; `session/reduce.ts`, `session/v2.ts`; `ApprovalCard.tsx` and `ActivityTimeline.tsx`.

Add typed setting/decision-source fields to the API and session projections. Apply `bot.autopilot.changed` only in ordered replay, and restore its state from snapshots after refresh/retention gaps. A delayed HTTP receipt or older snapshot must not overwrite a newer setting revision. Use the same query/session source for both toggle placements.

Include decision source and Autopilot revision in approval resolution, action-start projections, and durable action history. Reconstruct **Auto-approved by Autopilot** after refresh even when there was never a pending approval card. Keep the mode badge distinct from connection health, human-control state, and run success.

## AP4 — Verify and document

| Area | Acceptance evidence |
| --- | --- |
| Defaults/persistence | Existing and newly created bots start off; enable/disable persists across refresh, two tabs, reset and backend restart. |
| Access | Owner can update; operator/viewer/foreign user cannot. Operators still require an execution grant to run a bot whose owner enabled Autopilot. |
| Pending and future requests | Enable while waiting resumes that request exactly once; later requests execute without a browser observer. Cover operations with no reusable policy scope. |
| Adapters/entry points | Both real adapters, skill replay, connector calls, routines and handoffs use the same setting and audit source. A different target bot remains unaffected. |
| Disable/races | Disable before claim prevents dispatch; disable after claim preserves the actual running outcome. Cover duplicate/stale updates, manual denial, expiry, Stop, takeover, and disable/re-enable revision fencing. |
| Policies | Off preserves exact-policy behavior. On approves across selected routine policy restrictions; off restores them. Revoked credentials/grants still prevent execution. |
| Recovery | Restart after a setting commit preserves state; unfinished runs stay interrupted. No run, tool call, or connector side effect is automatically resubmitted. |
| UI | Checkbox saves once, reverts on error, is read-only where required, and synchronizes between views/tabs. Attribution survives refresh. Verify compact/expanded/mobile layouts without adding controls to the fixed icon row. |

Extend the existing backend approval/automation suites and frontend protocol/Playwright scenarios. Include a real-Docker action that completes unattended when enabled and waits for ordinary approval after disabling. Use controlled HTTP responses for connector tests; cloud publication is not required to validate the toggle.

Update the runtime/frontend guides and implementation record after implementation, especially the existing statements that group routines require human approval and routine automatic decisions always require a selected exact policy. Describe those as the defaults with Autopilot off, with the explicit owner-enabled exception.

Delivery order: **AP1 storage/API → AP2 runtime decisions → AP3 UI/history → AP4 verification/docs**. Completion means one owner-controlled checkbox approves valid pending and future requests for that bot, operates without an observer, records its decisions, and returns to existing approval behavior when unchecked.
