# SRS-005 Protocols and API

Wire contracts. Domain states are in [002-domain-model-and-persistence.md](002-domain-model-and-persistence.md). The SPA uses only protocol v2.

## Accounts and catalog

Unsafe methods MUST require `Content-Type: application/json` and a JSON object body, or return 415. Unknown or foreign ids MUST return 404. Registration MUST close when `ALLOW_REGISTER=0`.

| ID | Route | Requirement |
| --- | --- | --- |
| PRT-001 | `POST /api/register`, `POST /api/login`, `POST /api/logout`, `GET /api/me` | Login and registration limits are in `SEC`. Logout revokes that login's subscriptions. Already accepted v2 runs continue under their deadlines. |
| PRT-002 | `GET/POST /api/credentials`, `PATCH/DELETE /api/credentials/{id}` | Secret MUST NOT be returned. Provider immutable. Delete returns 409 while a bot uses it. |
| PRT-003 | `GET/POST /api/bots`, `GET/PATCH/DELETE /api/bots/{id}` | Framework immutable. Credential must be owned and compatible. Delete closes the sandbox, drops the transcript, and deletes the row. `GET` includes messages. |
| PRT-004 | `GET /health` | Process liveness only. |
| PRT-005 | `GET /ready` | MUST return 503 until startup and recovery finish, persistence fails, or a required worker has stopped or stalled. Required workers MUST include runtime cleanup, computer monitoring, control leases, routines, channels, and capture cleanup. |
| PRT-006 | `GET /api/capabilities` | Protocol version and feature flags. MUST NOT start a computer. The UI MUST enable a control only when the flag is advertised. |

## Protocol v2 commands

`request_id` MUST be 8–128 characters matching `[A-Za-z0-9_-]`. Bodies MUST use Pydantic `extra="forbid"`. An identical retry MUST return the original receipt. The same id with a different payload MUST return 409. A lost HTTP response MUST NOT cause an automatic retry; the client keeps the id for an explicit retry.

| ID | Route | Requirement |
| --- | --- | --- |
| PRT-007 | `GET /api/bots/{id}/snapshot` | Consistent view at `snapshot_seq`: computer, latest run, last 200 messages, up to 500 events, pending approvals, history cursor. Shared computers add `scope`, `workspace_id`, and `attached_bot_ids`. |
| PRT-008 | `GET /api/bots/{id}/messages?before=` | Older messages, 200 at a time, with stable ids and server times where known. |
| PRT-009 | `GET /api/bots/{id}/events?after_seq=` | At most 100 committed events. A cursor below `floor_seq` MUST report `resync_required`. |
| PRT-010 | `POST /api/bots/{id}/runs` | Body `{request_id, prompt}` plus optional attachment ids. Prompt MUST be at most 32000 characters. Returns 202 and the admitted run, or 409 when a run is active. Over capacity returns 429 `capacity_limit` with `Retry-After: 5`. |
| PRT-011 | `GET /api/bots/{id}/runs/{run_id}` | Persisted status, configuration reference, principal, timestamps, and outcome. |
| PRT-012 | `POST /api/bots/{id}/runs/{run_id}/stop` | Returns `stopping` first. Acknowledgement is not confirmed termination. |
| PRT-013 | `POST /api/bots/{id}/approvals/{aid}/decision` | Body `{request_id, decision, revision}` where `decision` is `approve` or `deny`. `expected_revision` MUST be accepted as the same field. Compare-and-set commits `approval.resolved` before `action.started`. Stale revision, expiry, or conflict MUST return HTTP 200 with `accepted: false` and the current status. Foreign ids return 404. |
| PRT-014 | `POST /api/bots/{id}/computer/close` | Body `{request_id, session_id}`. An outdated instance MUST be rejected so a retry cannot close the replacement. |
| PRT-015 | `GET /api/bots/{id}/captures/{cid}` | PNG bytes, `private`/`no-store`, `nosniff`. Missing or expired returns 404. |
| PRT-016 | `WS /api/bots/{id}/events/ws?after_seq=` | Observe only. Order MUST be snapshot when needed, then `ready`, then committed envelopes. No command frames. Authorization MUST be rechecked before protected sends and at least every 5 seconds. Sends MUST be bounded to 5 seconds. A slow consumer MUST disconnect and recover from the durable cursor. |

## Event envelope

| ID | Requirement |
| --- | --- |
| PRT-017 | Schema version MUST be 2. Each envelope MUST include `event_id`, per-bot `seq`, `workspace_id`, `bot_id`, `session_id`, `generation`, `run_id`, `action_id`, `occurred_at` as UTC ISO-8601, `type`, and `data`. Session, run, and action refs MAY be null outside those lifecycles. |
| PRT-018 | Implemented types MUST include `run.started`, `session.bound`, `message.created`, `observation` (a sanitized v1 frame), `capture.available`, `approval.required`, `approval.resolved`, `run.stopping`, `run.finished`, and `session.<status>`. Further families MUST include `action.started`, `action.completed`, `action.failed`, `plan.updated`, `bot.autopilot.changed`, `policy.*`, `filesystem.changed`, and `control.*`. Clients MUST ignore unknown types. |
| PRT-019 | Text fields on events MUST be bounded to 64000 characters. Known model keys, URL userinfo, and query parameters named `sig`, `token`, `api_key`, or `access_token` MUST be redacted before persistence. |
| PRT-020 | Snapshot-then-replay after `snapshot_seq` MUST be gap-free and duplicate-free. A commit-before-publish crash MUST still deliver the event on the next read. |
| PRT-021 | The wire schema exporter MUST be side-effect-free. `scripts/check_wire.py` MUST fail when `agentbot_control.wire` drifts from `src/api/events.generated.ts`. |

## Legacy control-plane socket

| ID | Requirement |
| --- | --- |
| PRT-022 | `WS /ws` MUST remain a compatibility facade over the same coordinator. It MUST accept `start` with `bot_id` and `prompt`, and MUST reject `framework` and `session_id`. `approve`, `stop`, and `close` MUST use the v1 messages. |
| PRT-023 | The facade MUST translate envelopes back to v1 frames. A disconnect MUST cancel only the run that this socket created. Removal of `/ws` MUST wait for a consumer inventory and the retention window in [021-foundation-operations.md](../021-foundation-operations.md): deprecation starts with the release that announces it and lasts at least through the next minor release. |
| PRT-024 | v1 server frames MUST be `session`, `log`, `artifact_written`, `approval_required`, `done`, `error`, and `closed`. `session` MUST be sent before the sandbox is ready and MUST NOT prove a live computer. |

## Raw gateway socket

| ID | Requirement |
| --- | --- |
| PRT-025 | `agentbot` MUST serve `WS /ws` with no account. `start` MUST require `framework` and `prompt` and MAY include `session_id`. The server MUST emit `session`, then log, artifact, and screenshot frames, then `done`. |
| PRT-026 | `approve` MUST carry `approval_id` and `decision` of `approve` or `deny`. `stop` MUST cancel the current turn. `close` MUST remove that session's container. |
| PRT-027 | The raw gateway MUST NOT inherit a bot's Autopilot setting, approval policies, or vault keys. It MUST NOT run on the same port as the control plane. |

## Authorization on every route

| ID | Requirement |
| --- | --- |
| PRT-028 | Every route and subscription MUST resolve the caller, workspace membership or an explicit share grant, and the bot. Operators MUST have a separate execution grant to mutate. Viewers MUST NOT execute. |
| PRT-029 | Origin allowlisting MUST apply to unsafe HTTP methods and WebSocket upgrade. Requests with no `Origin` (tests and non-browser clients) MUST still be accepted. A wildcard CORS origin MUST fail startup. `COOKIE_SAMESITE=none` without `COOKIE_SECURE=1` MUST fail startup. An empty `AGENTBOT_SECRET` MUST fail startup. |
| PRT-030 | Long-lived subscriptions MUST recheck login and authorization. Authentication only at connect time is not sufficient. Logout, revoked membership, and revoked shares MUST terminate streams. |
| PRT-031 | The client MUST NOT supply a Docker container id or a filesystem root. The server chooses both. |

## Workspace deletion API

| ID | Requirement |
| --- | --- |
| PRT-032 | Workspace deletion MUST expose preview, strict idempotent deletion, owner history/status and cleanup retry routes as specified in [027](../027-workspace-deletion.md). Receipt replay MUST precede active membership checks. Unauthorized requests MUST return 404; stale impact, changed request inputs and blockers MUST return 409. |
| PRT-033 | Deletion request/response contracts MUST be exported without application startup and included in generated schema/TypeScript drift checks. The feature MUST reuse the current v2 stream permission boundary. |

## Traceability

| IDs | Sources |
| --- | --- |
| PRT-001–PRT-006 | Blueprint §§8–9; [016](../016-agent-control-backend-runtime.md); [021](../021-foundation-operations.md) |
| PRT-007–PRT-021 | Blueprint §8.3; [009](../009-agent-control-frontend.md); ADR-0011, ADR-0017 |
| PRT-022–PRT-027 | Blueprint §§8.1–8.3; README |
| PRT-028–PRT-031 | Blueprint §10; [016](../016-agent-control-backend-runtime.md) |
