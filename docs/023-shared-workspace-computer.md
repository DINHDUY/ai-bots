# Shared workspace computer

A workspace owner can choose one computer for every eligible bot in that workspace. The default remains one live computer per bot ([ADR-0002](adr/0002-container-per-bot.md), qualified by [ADR-0018](adr/0018-optional-shared-workspace-computer.md)).

[Markdown workflow imports](025-markdown-workflow-import.md) create their new
workspace in shared Docker mode by default. The reviewed import saves computer
settings without creating a computer; the owner starts it through the existing
workspace controls. Ordinary workspace creation keeps the per-bot default.

## Mode

`per_bot` (default) keeps today's behavior. `shared` attaches eligible bots to a single `computer_sessions` row whose `bot_id` is null and whose `workspace_id` is set. Eligible bots use the Docker sandbox or an Azure cloud computer. Microsoft UFO bots and bots paired with a Windows PC keep their own computer.

Only the workspace owner can change the mode, and only by sending the current revision. The change is rejected with `computers_active` while any eligible bot still has a non-closed computer, or while the shared computer itself is not closed. Nothing is copied between modes. Per-bot cloud configuration is locked while shared mode is on. The shared cloud computer uses a workspace compute profile.

## Runs and lifecycle

Bot runs reference the shared session. They do not create a computer. If the shared computer is not running, the run is rejected with `workspace_computer`. Runs may overlap. Bash, file writes, browser actions, and desktop actions take the existing per-session lock, so those actions run one at a time. They still share the desktop, browser tabs, files, and processes.

Bot-level create, reset, hibernate, close, and cloud lifecycle actions are rejected with `workspace_computer`. The owner uses `POST /api/workspaces/{id}/computer/lifecycle`. Those actions are rejected with `computer_busy` while any run or human lease is bound to the shared computer.

Deleting an idle bot while the shared computer is closed removes its bot records
and retains its channel tombstone without invoking bot-level computer retirement.
Deletion is rejected while the shared computer is open or that bot has an active
task; a rejected deletion leaves its collaboration enrollment intact.

A human lease on the shared computer pauses every attached bot. Approvals, Autopilot, credentials, and transcripts stay per bot. The shared computer counts once toward capacity and is charged to the workspace owner.

Status changes are written in the same transaction to every attached bot's event stream. Snapshots report `computer.scope = "workspace"` plus `workspace_id` and `attached_bot_ids`.

## API

- `GET /api/workspaces/{id}/computer` shows the mode, provider, computer, and attached bots.
- `PUT /api/workspaces/{id}/computer` changes mode, provider, profile, and ownership.
- `POST /api/workspaces/{id}/computer/lifecycle` runs create, close, reset, hibernate, resume, keep-warm, and the cloud attach/start/stop/delete actions.
