**Agent Bot UI Design**  

Historical visual specification. Current approval behavior is server-owned; the old Always allow mockup does not describe the current SPA. See the [frontend contract](009-agent-control-frontend.md).
Agentic, persistent workspace for multi-bot collaboration (desktop-first, responsive to mobile). Dark, high-clarity aesthetic aligned with xAI/Grok: deep charcoal/black bases, electric cyan/violet accents, high-contrast readable text, subtle glassmorphism and soft glows for live activity states.

### Design Principles
- **Transparency first**: Always show *what the bot is doing* (live VM view) alongside conversation.
- **Conversation as the control plane**: No complex workflow builders; chat + lightweight visual controls.
- **Parallelism without chaos**: Multiple bots visible and able to talk to each other.
- **Human-in-the-loop by default**: Explicit, non-modal approval gates for sensitive actions.
- **Progressive disclosure**: Simple by default, power features (Teach Task, Routines, marketplace) one click away.
- **Cross-platform consistency**: Same information architecture on macOS/Windows/Linux; adapted density and touch targets on iOS/Android.

### Overall Layout (Desktop)
Three-zone primary layout with optional fourth zone:

```
┌─────────────────────────────────────────────────────────────────────┐
│  Top Bar (global)                                                   │
│  [Agent Bot logo]  Workspace switcher  Search  + New Bot  Notifications  User │
├──────────────┬──────────────────────────────────────┬───────────────┤
│              │                                      │               │
│  Left Rail   │         Center Stage                 │  Right Panel  │
│  (240–280px) │     (flexible, primary focus)        │  (320–400px)  │
│              │                                      │               │
│  • Bots list │  Conversational Messaging Hub        │  Live Workspace│
│  • Groups    │  + inline approvals, Teach Task,     │  (VM view)    │
│  • Routines  │    Routines, status chips            │  • Browser    │
│  • Marketplace│                                     │  • Terminal   │
│  • Settings  │                                      │  • Filesystem │
│              │                                      │  • Activity   │
└──────────────┴──────────────────────────────────────┴───────────────┘
```

- **Collapsible left rail** (can pin or auto-hide).
- **Right panel** can be toggled to full-width or split further (e.g., side-by-side browser + terminal).
- Persistent cloud session indicator (green pulse + “VM alive · 2h 14m”) always visible in the top bar or right panel header.

### Key Screens & Components

**1. Multi-Bot Panel & Left Rail**
- List of named bots with status:
  - Avatar + name
  - Status chip: Idle / Thinking / Working / Waiting for approval / Error
  - Last activity timestamp + short preview
  - Unread badge
- Group chat section below: “Sales + Reporting Squad”, “Dev Assist”, etc.
- Drag-and-drop to reorder or create groups.
- “+ New Bot” opens a lightweight modal: name, personality/role (optional prompt), starting skills.

**2. Conversational Messaging Hub (Center)**
- Clean message list with:
  - User messages (right-aligned, subtle background)
  - Bot messages (left-aligned, avatar + name)
  - System / inter-bot messages (centered or distinct style, e.g. “Sales Bot → Reporting Bot: Here’s the lead list”)
- Rich message types:
  - Text + markdown
  - Inline approval cards
  - Live progress cards (“Browsing LinkedIn…”, “Writing report…”)
  - File/artifact previews
  - “Teach a Task” recording indicator
- Input bar at bottom:
  - Multi-line text + voice/dictation button
  - Attachment, @mention bot, /commands
  - “Teach a Task” toggle (records user steps when active)
  - “Create Routine” quick button

**3. Live Cloud Computer Workspace (Right Panel)**
Tabbed or segmented control:
- **Browser** — full interactive virtual browser window (screenshot stream + cursor highlight when bot is using it). User can take control or watch.
- **Terminal** — live shell output with syntax highlighting.
- **Filesystem** — tree view + file previews, with change highlights.
- **Activity Feed** — chronological log of actions (tool calls, decisions, approvals).
- Header shows: session name, VM status, “Open full screen”, “Share session”, “Reset”.

When the bot is using computer-use vision, the browser tab shows a soft cyan border pulse + “Bot is navigating…”.

**4. Approval Gates (Inline, Non-Modal)**
Appears as a distinct card inside the message stream or as a floating action bar:

```
┌──────────────────────────────────────────────────────┐
│ ⚠️  Action requires approval                          │
│ Send email to 12 prospects via Gmail                 │
│ [Preview draft]                                      │
│                                                      │
│ [Deny]   [Allow once]   [Always allow this action]   │
└──────────────────────────────────────────────────────┘
```

- Color-coded severity (yellow = medium, red = high).
- “Always allow” creates a reusable Auto-Review rule that can later be managed in Settings.

**5. Teach a Task & Routines**
- “Teach a Task” toggle in the input bar or floating in the workspace view. When active: red recording indicator + “Stop & Save Skill”.
- After recording → modal to name the skill, describe it, and optionally add to a bot’s permanent toolkit.
- “Create Routine” opens a simple scheduler: trigger (time, webhook, event), assigned bot(s), description. Appears in the left-rail Routines section.

**6. Marketplace / Connect Library**
Accessible from left rail or top-level “+ Connect”.
- Categories: Agent Orchestration, Canvas, Productivity, MCP Servers, Communication, CRM, Dev Tools.
- Card grid with search + filters.
- Each connector shows: logo, status (Connected / Needs auth / Available), “Connect” or “Manage” button.
- Popular ones pre-highlighted: Google Workspace, Slack, Notion, Salesforce, Microsoft 365, GitHub, Jira, etc.

**7. Group Chat Spaces**
Same messaging hub as 1:1, but:
- Multiple bot avatars in the header.
- Inter-bot messages are visually distinct (smaller, different background, “Bot A → Bot B”).
- User can still @ any bot or the whole group.
- Shared context panel (optional) showing collective memory / shared files.

### Visual Design System
- **Background**: `#0B0C0F` / `#111216`
- **Surfaces**: `#1A1B1F` with 8–12% white glass overlays
- **Accent**: Cyan `#00E5FF` (live activity, primary CTAs) + soft violet `#A78BFA` for secondary
- **Text**: Primary `#F4F4F5`, secondary `#A1A1AA`
- **Status colors**: Green (active), Amber (waiting), Red (blocked/error), Blue (thinking)
- **Typography**: Inter or SF Pro-like system font; monospace for terminal/code
- **Radius**: 12–16px cards, 8px controls
- **Motion**: Subtle pulse on live elements, smooth expand/collapse of panels, micro-interactions on approvals

### Mobile Adaptations (iOS / Android)
- Bottom tab bar: Bots | Chats | Workspace | Marketplace | More
- Chat becomes full-screen; swipe or button to reveal Live Workspace as a bottom sheet or second tab.
- Approvals remain large, thumb-friendly cards.
- Voice input elevated (dictation primary on mobile).
- Multi-bot coordination still possible via group chats; live VM view is view-only or limited interaction.

### Additional UX Details
- Global search: bots, past chats, skills, files, routines.
- Notification center: approvals pending, routine completions, inter-bot handoffs.
- Session persistence: every bot keeps its own cloud VM; users can “hibernate” or “keep warm”.
- Accessibility: full keyboard navigation, high-contrast mode, screen-reader labels on all live status indicators.
- Onboarding: first-run guided tour that creates one bot and shows the live workspace in action.

This design turns Agent Bot into a true multi-agent operating system rather than a chat window: conversation is the interface, the cloud computer is always visible, and human control remains explicit and lightweight.
