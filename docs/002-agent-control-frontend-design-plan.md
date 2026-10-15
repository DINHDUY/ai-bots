# Apply the Agent Control design to the frontend

Historical frontend design plan. The current SPA requires v2 and has removed page-local automatic approval; see the [frontend contract](009-agent-control-frontend.md).

Status: frontend milestones 1–6 implemented in `packages/agent-control-frontend`. See [frontend usage and verification](009-agent-control-frontend.md). The backend-dependent capabilities are planned in [Implement the deferred Agent Control capabilities](018-agent-control-backend-features-plan.md). The sequence below records the frontend implementation scope and acceptance criteria.

Apply the [design system](001-agent-control-design-system.md) and [three visual mockups](mockups/agent-control/README.md) to `packages/agent-control-frontend`. Build the main workspace, expanded cloud computer, and file/activity inspection views using the existing React application and real session data.

The first release is a frontend redesign with limited additions to client-side presentation state. Backend-dependent capabilities are a follow-up milestone. Keep React, TypeScript, Vite, CSS Modules, TanStack Query, Zustand, and HashRouter.

## Target screens

| Reference | Production behavior |
| --- | --- |
| [01 — Main workspace](mockups/agent-control/exports/01-main-workspace.png) | Global header; collapsible bot rail; conversation with inline approvals and anchored composer; compact Live Cloud Computer panel. |
| [02 — Expanded computer](mockups/agent-control/exports/02-live-cloud-computer.png) | Collapse the rail, expand the existing computer view, optionally show screen and terminal together, and show session context and activity on the right. |
| [03 — Files and activity](mockups/agent-control/exports/03-files-and-activity.png) | Show files observed in this session as a tree, select a file to view its reported preview, and inspect related session activity. |

Use the mockups for hierarchy, color, spacing, and component treatment. Render actual captures and event content. Sample bots, ETL metrics, report pages, timestamps, and handoffs belong in test fixtures only.

## What is available today

The existing frontend already implements authentication, credential management, bot creation/settings/deletion, the overview, chat, approval decisions, terminal output, screenshots with history, artifact previews, and the ETL preset.

The main structural gaps are:

- `App.tsx` puts the header inside the content column. The target header spans the entire application.
- `BotWorkspace.tsx` renders the entire settings form before the conversation. Move settings behind a header action so the workspace fills the viewport.
- `workspace.module.css` allocates nearly half the available width to the computer. The target compact panel is 320–400 px wide.
- `LiveScreen.tsx`, `TerminalPane.tsx`, `FilesPane.tsx`, and `ActivityTimeline.tsx` are usable data-driven foundations with minimal presentation.
- `BotSession` currently discards the received session ID, stores activity as strings, and has no connection state or event timestamps.
- One WebSocket per bot is essential: log frames do not carry a bot/session ID. Expanding a panel or switching tabs must keep the same connection and session store.

## First-release scope and data boundaries

| Design feature | First-release implementation | Dependency for the full design |
| --- | --- | --- |
| Bot avatars, status, activity preview | Stable initials/icon and color from bot ID; use actual session status and observed activity. Show pending-approval counts. | Saved avatar/role metadata and durable unread state if needed later. |
| Global header/search | Brand, existing New Bot action, user menu, API keys, theme, sign out; search the loaded bot list with a clearly scoped “Search bots” label. | Workspace catalog/switching and server search across transcripts, skills, and files. |
| Notification indicator | Count pending approvals from current bot sessions; each item links to the relevant conversation. | Durable notifications, routine completion, and handoff events. |
| Live computer status | Show connection status, task state, actual session ID when received, and age of the last capture. | Sandbox health, creation time, capabilities, and authoritative uptime. |
| Screen/browser view | Keep a neutral **Screen** tab while capture provenance is unknown. Display the supplied image with its natural aspect ratio, fit/zoom, history, and “Latest capture” state. | Explicit browser/desktop source, current URL, cursor coordinates, and action-in-progress events before adding “Browser” or “Bot is navigating.” |
| Terminal | Format existing command/output entries; allow copy and follow-latest with user-controlled scrolling. | A PTY/stream protocol for interactive input and incremental output; explicit exit codes for success badges. |
| Filesystem | Build a tree from `artifact_written` paths, select the latest reported version per path, and label it “Observed files” / “Reported preview.” | Complete listing, MIME/size/truncation metadata, full content/download endpoints, and file change notifications. |
| Activity and progress | Combine supported events into a chronological local timeline; show latest operation and task status. | Structured plan/step events before showing step counts or percentages. |
| Inline approvals | Retain exact action/detail and approval ID; style amber cards with Allow once, Deny, and Always allow. Show local decisions explicitly. | Server acknowledgement/expiry and persistent, narrowly scoped policy rules. |
| Session actions | Expand/collapse and return to chat are frontend actions. Keep the existing **Stop** and **Close sandbox** semantics. | Remote input ownership, session sharing, reset/recreate, hibernation, and keep-warm APIs. |
| Groups, handoffs, teaching, routines, attachments, marketplace | Add these controls when their workflows have backing functionality. | Dedicated data models, APIs, permissions, and events. |

Important contract details:

- `session` is emitted before the kernel finishes sandbox initialization. Neither that frame nor an open WebSocket proves “VM alive.” A reconnect likewise does not restore the active turn or its pending approvals.
- Screenshot `source` currently identifies the adapter, not whether the image came from Chromium or Xvfb. The headless Playwright browser and Xvfb desktop are separate surfaces. Do not wrap screenshots in invented browser chrome or paint a synthetic agent cursor over them.
- Artifact previews may be only the first 200 characters. Files produced inside a bash command are not automatically reported as `artifact_written`. A missing tree entry does not prove the file is absent; a short preview is not a complete downloadable file. Do not infer cloud publication from a local file write.
- Existing transcript history has no timestamps. Record new event receipt times in the client; omit unknown historical times. Bot `updated_at` is configuration metadata, not last execution time.
- Always-allow currently matches the action name, such as `bash`, for that bot in the current page session. The UI must explain that breadth and lifetime rather than implying it authorizes only the displayed command or saves a server rule.
- Closing a sandbox removes its workspace. Remaining images and previews are historical observations and must not appear to be current files or a live screen.

## Component and state organization

Keep existing feature directories and introduce a small shared presentation layer:

```text
src/
  components/ui/
    Icon.tsx
    Button.tsx
    Avatar.tsx
    StatusBadge.tsx
    EmptyState.tsx
    Dialog.tsx
  features/shell/
    AppShell.tsx
    GlobalHeader.tsx
    shell.module.css
  features/bots/
    Sidebar.tsx                 # rework existing component
    BotWorkspace.tsx            # assemble views for the selected bot
    BotHeader.tsx
    BotSettings.tsx             # existing form inside settings dialog
  features/chat/
    Transcript.tsx
    ApprovalCard.tsx
    Composer.tsx
  features/workspace/
    Workspace.tsx               # same data source in compact/expanded views
    WorkspaceHeader.tsx
    SessionContext.tsx
    LiveScreen.tsx
    TerminalPane.tsx
    FilesPane.tsx
    ActivityTimeline.tsx
  session/
    reduce.ts                   # pure event reduction
    store.ts                    # existing per-bot sessions/actions
    botSocket.ts                # existing transport + connection callbacks
    selectors.ts               # status, latest activity, observed file tree
    workspaceUiStore.ts         # per-bot drafts/selection and layout preferences
  styles/
    tokens.css
    global.css
```

Use a small typed SVG icon component based on the mockup's existing line icons. Convert the useful CSS into tokens and CSS Modules. Rebuild the mockup's markup as React components; its global DOM handlers, `innerHTML` templates, and fixture state are prototype code.

Separate state responsibilities:

- **TanStack Query:** user, bots, credentials, bot details, and transcript loading.
- **Session store:** received frames, decisions, terminal entries, artifact observations, captures, actual session ID, and connection state. Retain server payloads rather than replacing them with display labels.
- **UI state:** draft and selected file/capture per bot, rail collapse, follow-latest, inspector visibility, and settings dialog. Clear user-scoped state on sign-out. Keep potentially sensitive drafts in memory; persist only benign preferences such as theme and rail collapse.
- **URL:** selected bot, view, tab, and expanded layout. Keep existing routes and HashRouter; validate unsupported query values and fall back to defaults.

Example URLs:

```text
#/bots/:id
#/bots/:id?view=computer&tab=screen&layout=split
#/bots/:id?view=computer&tab=files
#/bots/:id?view=computer&tab=activity
```

Expand/return and browser back/forward must preserve drafts, capture selection, file selection, scroll position where practical, and the owning bot's socket. `#/overview` and `#/keys` continue to work.

## Implementation sequence

### 1. Establish tokens and shared controls

Files: `styles/global.css`, new `styles/tokens.css`, `components/ui/*`.

- Define the documented backgrounds, surfaces, cyan/violet accents, text colors, and green/amber/red/blue status tokens; add spacing, typography, radius, border, focus, and motion tokens.
- Make the documented dark palette the default. Preserve the existing explicit light-theme option with accessible neutral tokens; persist the chosen theme.
- Use Inter when locally available, with Segoe UI/system fallbacks, and Cascadia/Consolas/system monospace. Avoid requiring a font network request.
- Establish buttons, icon buttons, badges, avatars, empty states, and an accessible native-dialog wrapper. Use 12–16 px card radii and 8 px control radii.
- Use readable production type sizes, visible keyboard focus, sufficient contrast, and reduced-motion support. Tiny labels within the mockup's simulated desktop are not application typography specifications.

Completion: existing pages still function and share the new palette and controls; authentication and API-key forms remain legible in both themes.

### 2. Rebuild the shell and primary workspace

Files: `App.tsx`, new `features/shell/*`, `Sidebar.tsx`, `BotWorkspace.tsx`, `BotHeader.tsx`, associated CSS Modules.

- Extract the shell while retaining the auth gate, QueryClient, routes, and shell-owned bot connections.
- Use a 68 px global header, a 248 px expanded rail, a flexible conversation, and a 400 px compact computer panel at the 1600 × 1000 reference viewport.
- Add real bot identity/status, pending-approval counts, active selection, overview navigation, scoped bot search, and a user menu containing API keys, theme, and sign out.
- Place bot settings behind the bot header's Settings action. Reuse credential filtering, model/name/instruction editing, ETL instructions, rule revocation, and delete behavior in the dialog.
- Keep the existing New Bot workflow and ETL preset. Use a read-only account/workspace label until multiple workspaces exist.
- Give the app a `100dvh` grid with `minmax(0, 1fr)` tracks and `min-height: 0` on nested panes. Transcript and panel content scroll independently; the composer and session header remain visible.

Completion: reference-screen proportions are established, settings are one click away, and bot navigation does not reset active sessions.

### 3. Apply the conversation and approval design

Files: `Transcript.tsx`, `ApprovalCard.tsx`, `Composer.tsx`, `chat.module.css`, UI draft state.

- Render user messages with subtle right-aligned surfaces, bot messages with real bot identity, and distinct system/error messages. Keep thought disclosures collapsible.
- Support Markdown through `react-markdown` and `remark-gfm` with raw HTML disabled and safe link handling; preserve code blocks and long-text scrolling/wrapping.
- Style exact approval action/detail as an inline amber card. Keep command/file details inspectable without truncating what the user is approving. Reuse the same decision component in the overview.
- A click marks the local choice; it does not mark the operation successful. Success/failure comes from subsequent events. Disable duplicate decisions and make reconnect/unknown status visible.
- Explain “Always allow” as allowing the action category for this bot while the page session remains active; retain the existing rule revocation control.
- Anchor the composer, preserve drafts per bot, support Enter/Shift+Enter with IME composition handling, and keep Send, Stop, ETL prompt, and supported dictation accessible. Disable a new Send while the bot is busy; drafting can continue.
- Keep ETL prompt filling unsent. Use follow-latest scrolling only when the operator is near the bottom; otherwise expose a new-content affordance.
- Use event-backed activity text for progress. Do not synthesize a “2 of 3” plan or ETL totals from arbitrary chat text.

Completion: an operator can send a prompt, inspect the exact requested action, allow/deny it, and follow the real result in the redesigned conversation.

### 4. Build compact and expanded computer views

Files: `Workspace.tsx`, new `WorkspaceHeader.tsx`, `SessionContext.tsx`, `LiveScreen.tsx`, `TerminalPane.tsx`, `workspace.module.css`, URL/UI state.

- Add Live Cloud Computer framing, actual session identity, separate connection/task status, Screen / Terminal / Filesystem / Activity navigation, and expand/return controls.
- Compact mode prioritizes the latest capture, with a small terminal excerpt and recent observed files as space allows. Always retain access to every pane through the tabs.
- Expanded mode supports the screen above the terminal and a context/activity inspector; screen-only and terminal-only modes remain available. Reuse the same components and session data.
- Render actual screenshot dimensions using `object-fit: contain`; support fit, zoom, history, and a “Back to latest” action. A selected historical capture stays selected when a new frame arrives.
- Format terminal commands and outputs as escaped text. Copy copies the actual displayed data. Show only supported outcome information; existing tool-call text is not an interactive terminal stream.
- Add precise empty, awaiting-first-capture, reconnecting, disconnected, failed, and closed states. Keep historical observations visibly distinct from current execution.
- Present Close sandbox as the existing destructive workspace close operation, with an explanation of file removal; do not rename it Reset. Route layout changes never send stop/close/start frames.

Completion: screenshots 01 and 02 have functional equivalents, and expanding the computer does not create another socket or lose pending approvals.

### 5. Add file inspection and a structured local timeline

Files: `reduce.ts`, `store.ts`, `botSocket.ts`, new `selectors.ts`, `FilesPane.tsx`, `ActivityTimeline.tsx`, session tests.

- Retain `session_id`; add transport connection callbacks and a connection-state field separate from task status. Treat the status of an interrupted turn as unknown until observed again.
- Supply a receipt timestamp from the store to the pure reducer; do not call the clock inside reducers. Add local metadata to new messages/captures/artifacts without inventing timestamps for loaded history.
- Replace activity strings with typed records containing ID, kind, text, optional detail, and receipt time. Include tool results, artifacts, approvals/local decisions, done/error/closed, and connection transitions. Label it activity observed in this page session.
- Project artifact paths into a sorted folder tree. Normalize path separators for display, keep the original path for identity, select the latest observation per path, and retain write history in activity. Mark first observation as “Observed,” not proof that the file was newly created.
- Show the raw reported preview by default. Syntax coloring can be applied without claiming completeness. Only enable a parsed JSON/table view when complete content is explicitly available; a parseable prefix alone does not prove the whole artifact was received.
- Make sensitive configuration previews such as `.env` protected in the new presentation. This is a display rule, not a replacement for server-side redaction. Do not include previews in sidebar snippets or persist them in browser preferences.
- Keep complete-file downloads out of this milestone. Offer “Copy preview” for eligible visible text; no file-size, publication, or checksum claims without metadata.
- Bound screenshot history, for example to the most recent 30 captures, and clearly indicate discarded earlier captures. Avoid base64 captures or long transcripts in localStorage and render only necessary thumbnails/previews.

Completion: reference screen 03 works with actual observed artifacts and local history, including truncated previews, duplicate paths, and empty sessions.

### 6. Finish responsive behavior and verify the complete workflow

Files: shell/chat/workspace CSS Modules, overview/auth/settings/key components, existing tests, browser visual fixtures, frontend documentation.

- At widths ≥1280 px, use the full rail and 400 px computer panel. At 1024–1279 px, use a 240 px rail and 320 px panel when readable. At 768–1023 px, use a collapsed rail and switchable conversation/computer panes. Below 768 px, use full-screen content and bottom navigation for supported destinations: Bots, Chat, Computer, More.
- Keep approval controls large enough for touch, make the composer keyboard-aware, and prevent horizontal page overflow. Let long code/file paths scroll within their panes.
- Add tab arrow-key navigation, selected/controlled-panel semantics, dialog focus containment and restoration, concise live announcements, and reduced-motion behavior.
- Bring overview, auth, bot creation/settings, and API keys into the same visual system. Preserve error/loading/empty states and existing functions; do not add mock-only navigation entries.
- Add deterministic browser fixtures for the three reference states using sample ETL data. Reuse the existing MSW/FakeWebSocket approach where suitable; use browser request/WebSocket interception for screenshot runs. Fixture data must never load in normal production sessions.
- Add Playwright as development tooling for repeatable browser checks and screenshots; retain Vitest/Testing Library for state and interaction tests.
- Update `docs/009-agent-control-frontend.md` with the new routes/layout, status semantics, observed-file limits, and supported controls. Keep the original mockups as design references.

Completion: all first-release screens are reviewable at desktop/tablet/mobile sizes, tests pass, and the UI does not expose inert concept controls.

## Validation and acceptance

Run `npm run test` and `npm run build` in `packages/agent-control-frontend` during implementation. Run the added browser checks against the real built frontend with controlled fixture traffic.

Preserve the behavior already covered by `App.test.tsx` and `session/reduce.test.ts`:

- Sign in, create a bot, send a prompt, and answer the correct approval ID.
- Route frames to the socket's owning bot while multiple bots run.
- Add a Foundry credential and select compatible credentials/models for a bot.
- Fill the ETL preset/instructions without sending the prompt automatically.
- Map terminal, screenshot, file, error, done, and closed frames; preserve always-allow behavior and revocation.

Update navigation expectations to open the settings dialog explicitly instead of expecting the form immediately after creation. Keep assertions on user behavior and outbound frames rather than old markup or CSS class names.

Add focused checks for the new behavior:

1. Expand/return, tabs, and browser back/forward preserve drafts/selections and keep one socket per bot; view changes send no execution commands.
2. Approval remains reachable in the main view and through an approval indicator in expanded/mobile views; a local choice is not a success result.
3. Connection loss is distinguished from task completion or sandbox closure. Loaded history and stale captures do not receive invented live status or times.
4. Repeated artifact paths update the selected preview; truncated previews remain labeled previews; sensitive configuration is concealed; complete-file downloads are absent without a supporting contract.
5. An operator inspecting an old capture or earlier transcript is not forced back to the latest item.
6. Signed-out users cannot retain another user's draft/session presentation state after account switching.
7. Keyboard navigation, dialogs, tab semantics, and reduced motion work; content and controls have adequate contrast and accessible names.

Visual checks: 1600 × 1000 against each reference, 1366 × 768 for common laptop height, 1024 × 768, and 390 × 844. Verify no page-level horizontal overflow, no clipped approval/composer/footer, usable empty/error states, and readable real tool output. Production content may differ from the illustrated ETL report; compare design structure and supported behavior.

## Follow-up capabilities

These changes are not prerequisites for shipping the first redesign. Their implementation sequence, contracts, and acceptance criteria are now in the [backend capabilities plan](018-agent-control-backend-features-plan.md):

| Capability | Required work |
| --- | --- |
| Verified VM status/uptime | Owner-authorized session status/capability endpoint or events, sandbox start time, heartbeat, and idle-close notifications. |
| Browser/desktop labeling and live cursor | Add capture provenance, URL where applicable, dimensions, timestamps, and explicit action/cursor telemetry to sandbox events. |
| Take control | Browser/desktop input protocol, control ownership, agent pause/resume coordination, and reconnect/release semantics. |
| Interactive terminal | Per-session PTY stream with input/resize/output lifecycle and bounded buffering. |
| Complete filesystem and downloads | Owner-authorized list/read/download routes, path confinement, size/MIME/truncation metadata, redaction rules, and observations of files created by subprocesses. |
| Reliable progress and approval outcomes | Structured task steps and command outcomes; acknowledged/expired approval states and reconnect reconciliation. |
| Persistent approval policies | Server-side per-user/per-bot policy storage, explicit action/argument scope, audit records, and revocation. |
| Groups, handoffs, routines, teaching, sharing, workspaces | Separate product/API milestones with concrete ownership, persistence, scheduling, recording, and event contracts. |

Implement milestones 1–6 in order as reviewable changes. The frontend-only milestone is complete when the three layouts operate on real data, current workflows remain intact, and browser validation passes. The follow-up capabilities expand the design as their contracts become available.
