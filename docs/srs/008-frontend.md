# SRS-008 Frontend

The SPA contract. It observes server state and sends durable commands. It does not own execution. `INV-009` and `DEC-010` apply.

## Stack and boundaries

| ID | Requirement |
| --- | --- |
| FE-001 | The UI MUST be a React 19, TypeScript, and Vite SPA. Styling MUST use CSS Modules and design tokens. REST data MUST use TanStack Query. Live session state MUST use Zustand. Routing MUST be a hash router. Markdown MUST use `react-markdown` and `remark-gfm` with raw HTML disabled and remote images omitted. |
| FE-002 | Unit tests MUST use Vitest, Testing Library, and MSW. End-to-end tests MUST use Playwright. Tests MUST NOT live under `src/`. |
| FE-003 | The dev server MUST be `http://127.0.0.1:5174`. `VITE_API_BASE` MUST default to `http://127.0.0.1:8000`. Every `fetch` MUST send `credentials: "include"`. The WebSocket URL MUST be that base with `http` replaced by `ws`. |
| FE-004 | There MUST be no legacy transport fallback and no browser-owned automatic approval. A backend that is not v2 MUST surface a compatibility error. |
| FE-005 | `sessionConnection.ts` MUST validate snapshots and events against the generated JSON schema. Malformed or unsupported frames MUST cause a controlled resync or a compatibility error. |
| FE-006 | Commands MUST be HTTP calls with stable request ids. Reconnect MUST NOT queue commands and MUST NOT approve actions. Command controls MUST stay disabled until snapshot and replay catch-up. Ambiguous command ids MUST be preserved for an explicit retry. |
| FE-007 | One `SessionConnection` MUST exist per bot. Reducers MUST NOT emit automatic approval commands. Run and approval state MUST come from durable server snapshots and events. |

## Honesty

| ID | Requirement |
| --- | --- |
| FE-008 | "Connected to control" MUST describe the socket, not computer health. |
| FE-009 | Screenshots MUST be shown as captured, with the reported surface and provenance. The UI MUST NOT invent browser chrome or a cursor. Older servers that omit provenance MUST leave it unknown. |
| FE-010 | A preview MUST NOT be presented as a full download or as proof of an external publication. Complete downloads MUST bind the file revision. Protected configuration files MUST show metadata only. |
| FE-011 | Imported history MAY have unknown timestamps. New events MUST show server occurrence time. Client receipt time MUST stay a separate observation. |
| FE-012 | After close, retained captures and previews MUST be labeled historical. Historical and cropped images MUST be view-only. |
| FE-013 | Plans MUST appear only from `plan.updated`. The UI MUST NOT synthesize steps from prose or tool counts. Action-in-progress MUST appear only between `action.started` and `action.completed`. |
| FE-014 | An expired capture MUST show "Screenshot no longer available" and an explicit "View latest" action. Empty history MUST show "No retained screenshots". Human-control clicks and keys MUST be rejected against an expired capture. Releasing a held input MUST still be possible. |
| FE-015 | When Autopilot is not advertised, the checkbox MUST be disabled and MUST say the backend needs an update. |

## Layout and routes

| ID | Requirement |
| --- | --- |
| FE-016 | Desktop MUST show a global header (search, New bot, approval notifications, account), a collapsible bot rail, a conversation with an anchored composer and inline approval cards, and a Live Cloud Computer panel 320–400 px wide that can expand to a screen and terminal split. |
| FE-017 | Below 1024 px, chat and computer MUST be separate views. Phones MUST get bottom navigation: Bots, Chat, Computer, More. |
| FE-018 | Routes MUST encode view state and MUST NOT start or stop execution. Required hashes include `#/overview`, `#/keys`, `#/workspace`, `#/workspace?tab=notifications`, `#/shares/:id`, `#/bots/:id`, and `#/bots/:id?view=computer` with `tab` of `screen`, `files`, `activity`, or `terminal`, and `layout` of `split` or `single`. An unknown tab or layout MUST fall back to screen and split. |
| FE-019 | Verified viewports MUST include 1600×1000, 1366×768, 1024×768, and 390×844. |
| FE-020 | Drafts, selected captures and files, and transcript or terminal follow state MUST live in memory per bot, survive view changes, and clear on sign-out. Only theme and rail preferences MUST persist in `localStorage`. With v2, messages, runs, and approvals MUST be restored from the backend. |
| FE-021 | Enter MUST send. Shift+Enter MUST insert a newline. The default-prompt control MUST accept at most 8000 characters, hide when empty or whitespace, and fill the draft without sending. |
| FE-022 | The screen MUST keep at most 30 captures in the session filmstrip. Viewing an older capture MUST NOT jump when a new one arrives. Older pages MUST load from the authenticated history API. |
| FE-023 | A conversation that is following the latest message MUST advance the persisted read cursor. Sidebar unread counts MUST use that cursor. An older tab MUST NOT move it backward. |

## Autopilot and shared computer

| ID | Requirement |
| --- | --- |
| FE-024 | The Autopilot checkbox MUST appear above the composer (including mobile), near the top of bot settings, and in the Live Cloud Computer controls. It MUST default off, save immediately, and MUST NOT wait for the settings form Save button. Only the bot owner MAY change it. Other members MUST see the value and an explanation. |
| FE-025 | The label "Auto-approved by Autopilot" MUST appear with the result and MUST survive refresh, including the enabling owner and setting revision in the details. |
| FE-026 | In shared-computer mode the bot header MUST say "Shared workspace computer" and lifecycle links MUST go to the workspace tab. Per-bot create, hibernate, and reset MUST NOT be offered for the shared computer. |
| FE-027 | A non-UFO bot that is given a Windows PC selection MUST show an error. The UI MUST NOT silently ignore the save. |

## Workspace surfaces

| ID | Requirement |
| --- | --- |
| FE-028 | The workspace center MUST cover members, groups, routines, toolkit, notifications, search, profile, and shared viewing as separate modules. Computer capabilities MUST follow `GET /api/capabilities` and `CONTROL_WORKSPACE_FEATURES`. |
| FE-029 | Tool selection in New bot and Settings MUST be atomic. The UI MUST show binding readiness and a warning when a UFO bot has an empty selection. Removing a tool MUST NOT be described as uninstalling packages. |
| FE-030 | Human control MUST show the lease, renewal, and an explicit Resume agent action. Manual actions MUST be attributed to a human actor. The UI MUST NOT fabricate an agent action for them. |
| FE-031 | Uploads MUST show progress, cancel, and error. A closed or missing computer MUST show a lifecycle error rather than creating a sandbox. |

## Workspace deletion

| ID | Requirement |
| --- | --- |
| FE-032 | Workspace settings MUST place the Delete workspace panel at the bottom, collapsed by default. Expanding it MUST offer owner-only deletion with an impact preview, blocker controls, and exact-name confirmation. Personal workspace deletion MUST be unavailable. |
| FE-033 | Deletion recovery MUST preserve the original request ID across response loss and reload, show catalog success separately from file cleanup, and expose owner history and cleanup retry. |
| FE-034 | Workspace and channel selections MUST resolve against accessible workspaces, including stale URLs and other tabs. Deleted bot sessions and cached content MUST be retired. Deleted import receipts MUST show a historical deletion result without navigation or resubmission. |

See [workspace deletion](../027-workspace-deletion.md).

## Traceability

| IDs | Sources |
| --- | --- |
| FE-001–FE-015 | Blueprint §§8.4 and 12; [009](../009-agent-control-frontend.md); [001](../001-agent-control-design-system.md) |
| FE-016–FE-023 | Blueprint §12.4; [009](../009-agent-control-frontend.md); [002](../002-agent-control-frontend-design-plan.md) |
| FE-024–FE-031 | [009](../009-agent-control-frontend.md); [016](../016-agent-control-backend-runtime.md); [023](../023-shared-workspace-computer.md); [013](../013-agent-control-tool-libraries-runtime.md) |
