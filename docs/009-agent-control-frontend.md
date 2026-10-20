# Agent control frontend

`packages/agent-control-frontend` is the web UI for the control plane. It is a React app served on its own origin. The API stays in `packages/agent-control-backend` (`agentbot-control` on port 8000).

## Run

```bash
cd packages/agent-control-frontend
npm ci
npm run dev
```

The dev server is `http://127.0.0.1:5174`. `npm run build` writes a static bundle to `dist/`, which is not committed. `npm run preview` serves that bundle.

`VITE_API_BASE` (default `http://127.0.0.1:8000`) is the API origin. Every `fetch` sends cookies (`credentials: "include"`). The WebSocket URL is the same base with `http` replaced by `ws`.

## Workspace design

The frontend implements the first release of the [design plan](002-agent-control-frontend-design-plan.md), using the [design system](001-agent-control-design-system.md) and [mockups](mockups/agent-control/README.md). The application defaults to the charcoal/cyan theme; **My account** also offers a light theme.

- The global header contains bot search, New bot, pending-approval notifications, and the account menu. API keys and sign-out remain available.
- The desktop layout has a collapsible bot rail, conversation with an anchored composer, and a 320–400 px **Live Cloud Computer** panel. Bot settings opens from the conversation header.
- Expand the computer for a screen/terminal split with session context and activity. The Screen tab also supports a screen-only layout, fit/zoom, capture history, and Back to latest.
- **Filesystem** lists the live sandbox as a lazy directory tree, with bounded previews, complete revision-bound downloads, and subprocess-change refresh. Older servers retain the observed-artifact fallback.
- Below 1024 px, conversation and computer occupy separate views. On phones, bottom navigation provides Bots, Chat, Computer, and More.

Routes retain HashRouter:

```text
#/overview
#/keys
#/workspace
#/workspace?tab=notifications
#/shares/:id
#/bots/:id
#/bots/:id?view=computer&tab=screen&layout=split
#/bots/:id?view=computer&tab=screen&layout=single
#/bots/:id?view=computer&tab=files
#/bots/:id?view=computer&tab=activity
```

`tab` also accepts `terminal`. Unknown tab/layout values fall back to the default screen/split presentation. Expanding, returning, and changing tabs reuse the bot's socket; they do not start, stop, or close an execution.

Drafts, selected captures/files, and transcript/terminal follow state live in memory per bot. They survive view changes and clear on sign-out. Only theme and rail preferences are persisted in localStorage. With v2, message/run/approval state is restored from the backend; unsent drafts remain local. Markdown supports tables, links, and code, with raw HTML disabled and remote images omitted.

The composer supports Enter to send, Shift+Enter for a new line, Stop, an optional **Default Prompt** button, and dictation where the browser provides it. Configure **Default Prompt (optional)** in Bot Settings and save to show the button for that bot. Clicking it fills the editable draft without sending; an empty or whitespace-only setting hides it. The setting is stored with the bot and supports up to 8,000 characters. File attachments upload explicitly with progress/cancel/error and are included only when selected. Drafting remains available while a bot is busy. A new prompt can be sent once the bot is available, the agent is not paused for human control, and the connection is open.

## What the computer panel reports

With the B1–B11 backend, the frontend discovers v2 and restores runs, messages, approvals, action results, and explicit plans from server snapshots and ordered events. Refresh and transient connection loss do not end an accepted run. Approval cards distinguish submission, server acceptance, execution, and result. Earlier messages can be loaded in the conversation. See [runtime behavior, limits, rule scopes, and upgrade instructions](016-agent-control-backend-runtime.md). Features depend on backend capabilities, current permissions, and sandbox image compatibility.

**Connected to control** describes the WebSocket connection. The separate computer status uses inspected service health, Docker start time and observation age. The Screen tab distinguishes browser and desktop, shows server capture time and sanitized browser URL/title, and displays an observed desktop cursor only while fresh. Older servers retain receipt-time captures without invented provenance or uptime.

The screen retains 30 captures in its local filmstrip; the backend exposes retained capture history. Looking at an older capture does not jump to a new image when one arrives. Historical/cropped images are view-only. Take control acquires an exclusive tab-specific lease for the selected surface after the agent stops safely. Release and disconnect leave the agent paused; **Resume agent** explicitly starts a new observing turn to continue the previous task. While paused, this button appears above the chat message box (including mobile) and in the computer controls, independently of remote-input support. It stays disabled while human control is active or the user lacks execution access; release control in the tab holding it before resuming.

The live file service includes files created by bash and manual terminals. Each folder loads when it is opened, 200 names at a time. Preview labels report truncation; Download binds the complete version and cannot substitute changed bytes. Protected configuration files expose metadata only, enforced by the backend. On an older server, the observed-file fallback offers Copy preview and never represents that preview as a full download or proof of cloud publication.

The Terminal tab lazily loads xterm for a real lease-bound Bash PTY, with resize, interrupt, explicit close and output-gap display. Command results remain separate. Without PTY support it shows escaped command/output history. Reset, hibernate/resume, create and bounded keep-warm use server lifecycle commands and show retention/deadline information. Hibernate preserves workspace files, not running processes.

With v2, the activity feed uses retained server events, acknowledged decisions, and structured action outcomes. Terminal results show exit code, timeout/cancellation, and output truncation. A completed turn may include failed actions. Task progress stays indeterminate unless an adapter supplies an explicit plan with step IDs. A backend without v2 support produces an explicit compatibility error.

On a connection loss, controls stay disabled until the event subscription catches up. The server retains runs and approval lifecycles. Ambiguous HTTP request IDs remain available for an explicit retry; reconnect does not queue execution. A restart marks unfinished runs interrupted, and unverified computers require closure before another task. **Close sandbox** asks for confirmation because it removes workspace files.

**Workspace settings** provides workspace switching/creation, membership and explicit execution grants, selected authenticated shares, profile/sidebar preferences, notification history, authorized search, groups, toolkit, routines, and the computer tab. The computer tab is where an owner turns on one shared computer for the eligible bots in that workspace. When a bot is using that computer, its header says **Shared workspace computer** and links lifecycle actions back to the workspace tab instead of offering per-bot create, hibernate, or reset. A viewer cannot execute. Sharing defaults to no screen surfaces; recipients must sign in and owners can revoke access.

Visible conversations following their latest messages advance a persisted read cursor. Sidebar unread counts use that cursor after it has been established; older tabs cannot move it backward. Profile edits still use revision checks to avoid silent overwrites.

Group conversations accept explicit bot/group mentions, selected context, and bounded handoffs with links to each bot's run. Teach a Task records reviewed structured steps during human control, supports private input and parameter editing, and saves immutable skill versions for installation/replay. The curated connector is GitHub repository issues with a scoped fine-grained PAT, health, invocation, rotation, local revocation and uninstall. No unsupported provider cards or arbitrary executable packages are shown.

Routines support a bot task, installed skill/connection, or explicit group task; manual, interval/daily, signed webhook and allowlisted event triggers; schedule preview; queue/skip budgets; optional exact approval policy; and durable run history. Missing approval remains an approval request. Onboarding points to real API-key, bot-creation and explicitly submitted task flows. Full contracts and release limits are in the [backend capabilities implementation plan](018-agent-control-backend-features-plan.md) and [verification record](003-agent-control-implementation-status.md).

## Autopilot

The **Autopilot** checkbox appears directly above the chat message box (including mobile), near the top of **Bot settings**, and in **Live Cloud Computer** controls. It is off by default and saves immediately, independently of the settings form's Save button. Only the bot owner can change it; other workspace members see the current value and an explanation. If the running backend does not yet advertise Autopilot, chat and settings show a disabled checkbox with a backend-update message. Restart the updated backend after active work finishes to apply migration 012 and expose the API; the UI periodically rechecks availability.

Checking it approves valid pending and future requests for that bot, including scheduled runs and handoffs. It works without an open browser and persists across refresh, computer reset and backend restart. The checkbox displays the last server-confirmed state, disables while saving, and shows inline errors. Snapshots, events and revision checks keep all placements and other tabs synchronized. **Autopilot on** badges appear in the bot and computer headers and beside each bot's status in the left navigation. The collapsed sidebar uses a small marker and an Autopilot tooltip. Run status and pending approvals remain visible independently of this mode.

Unchecking restores manual approvals and existing exact rules, cancelling Autopilot authorizations that have not started execution. Already executing actions can finish; Stop remains available. Checking the box does not start a task or resume a paused computer. Permissions, credentials, context validation and execution limits continue to apply.

Approval cards and Activity show **Auto-approved by Autopilot**, with the enabling owner and revision in details. Accepted, executing and completed/failed results remain distinct, including after refresh. See the [runtime contract](016-agent-control-backend-runtime.md#autopilot).

## Cross-origin cookies

The backend allows browser calls only from origins listed in `CORS_ORIGINS`. Mutations and WebSockets reject any other `Origin`. Requests with no `Origin` header (tests and non-browser clients) still work. JSON commands require `application/json`; the upload endpoint accepts bounded multipart bodies.

`COOKIE_SAMESITE=lax` works for the dev pair, and for production hosts that share a site (for example `app.example.com` and `api.example.com`). `none` requires `COOKIE_SECURE=1` and still depends on the browser allowing third-party cookies.

## Commands, replay and presentation

The authenticated SPA requires v2 capabilities and opens one event subscription per observed bot. Commands use HTTP with stable request IDs. `sessionConnection.ts` validates snapshots/events against the generated JSON schema and catches up from a durable sequence cursor. Malformed or unsupported frames cause resync or a compatibility error. There is no legacy transport fallback and no browser-owned automatic approval.

The JSON schema is exported by `agentbot_control.wire` without application startup, then translated into `src/api/events.generated.ts`. `scripts/check_wire.py` rejects drift. Domain payloads inside events remain partly open objects; complete HTTP/domain schema coverage remains F5 work.

Pure presentation reducers still translate retained observations into terminal entries, images, artifacts and activity. Run status and approval outcomes come from durable server state. **Allow once**, **Deny**, exact server approval rules and owner-controlled Autopilot use the shared backend dispatcher. Saving a rule does not approve an outstanding request. The removed page-local Always allow rules are not migrated.

`WorkspaceCenter.tsx` owns workspace/tab selection. Members, groups, routines, toolkit, notifications, search and profile panels own their feature interactions in separate modules. `SharedView.tsx` is an independent route. Shared request helpers and local view contracts live in `workspaceApi.ts`; generated wire types remain under `src/api`. React Query owns fetched server data, the session store owns replay state, and local drafts/preferences stay with their components.

## Verification

Run from `packages/agent-control-frontend`:

```bash
npm run test
npm run build
npm run test:e2e
```

The browser suite needs Playwright Chromium (`npx playwright install chromium` if missing). `test:e2e` builds the production frontend and serves it on port 4173. Its API and WebSocket fixtures are confined to `e2e/`; no demonstration data is loaded in normal application sessions and no cloud calls are made by those fixtures.

Browser checks cover shared session navigation, approval messages, capture history, conversation follow/scroll restoration, file previews, keyboard tabs, connection interruption, settings focus restoration, theme/sign-out, and responsive layouts at 1600 × 1000, 1366 × 768, 1024 × 768, and 390 × 844. Screenshots are written under `packages/agent-control-frontend/test-results/`, which is ignored by Git.
