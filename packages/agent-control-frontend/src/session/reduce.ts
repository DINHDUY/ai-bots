import type { InboundFrame, OutboundFrame } from "../api/frames";
import type { TranscriptMessage } from "../api/client";

export type BotStatus =
  "idle" | "running" | "awaiting" | "stopping" | "closed" | "error" | "unknown";
export type ConnectionStatus =
  "connecting" | "connected" | "reconnecting" | "disconnected";
type Observed = { id: string; at?: number; order?: number };
type TextKind = "user" | "thought" | "assistant" | "error" | "system";
export type ChatItem = Observed &
  (
    | { [Kind in TextKind]: { kind: Kind; text: string } }[TextKind]
    | {
        kind: "approval";
        approvalId: string;
        action: string;
        detail: string;
        decision?: "approve" | "deny";
        decisionSource?: string;
        autopilotRevision?: number;
        decidedBy?: string;
        decisionReason?: string;
        stale?: boolean;
        acknowledged?: boolean;
        revision?: number;
        actionId?: string;
        actionStatus?: string;
        resultText?: string;
        policyScope?: string;
        expiresAt?: string;
      }
  );
export type TerminalEntry = Observed & {
  command: string;
  output: string;
  outcome?: string;
};
export type ActionState = {
  decisionSource?: string;
  autopilotRevision?: number;
  decidedBy?: string;
  operation: string;
  detail: string;
  status: string;
  stepId?: string;
  outcome?: string;
};
export type PlanStep = {
  id: string;
  title: string;
  status: "pending" | "running" | "completed" | "failed" | "cancelled";
};
export type FileEntry = Observed & { path: string; preview: string };
export type CaptureMetadata = {
  surface_id: string;
  surface_kind: "browser" | "desktop";
  width: number;
  height: number;
  captured_at: string;
  sequence: number;
  viewport_revision: string;
  url?: string;
  title?: string;
  cursor?: { x: number; y: number };
  transform?: { view_only?: boolean };
};
export type Health = {
  health: string;
  observed_at: string;
  started_at?: string;
  services: Record<string, boolean>;
  compatible?: boolean;
};
export type Shot = Observed & { src: string; capture?: CaptureMetadata; expiresAt?: string | null; storageSequence?: number };
export type ActivityEntry = Observed & {
  kind:
    | "tool"
    | "file"
    | "approval"
    | "decision"
    | "session"
    | "error"
    | "connection"
    | "result";
  text: string;
  detail?: string;
};
export type BotSession = {
  autopilot?: import("./autopilot").AutopilotState;
  protocol?: 2;
  serverSeq?: number;
  runId?: string;
  computerStatus?: string;
  health?: Health;
  capturesRevision?: number;
  capturesInvalidation?: number;
  removedCaptureIds?: string[];
  filesRevision?: number;
  toolsRevision?: number;
  messagesBefore?: number | null;
  observationsTruncated?: boolean;
  submitting?: boolean;
  submittingApprovalId?: string;
  actions?: Record<string, ActionState>;
  plan?: PlanStep[];
  commandError?: string;
  seq: number;
  seeded: boolean;
  status: BotStatus;
  connection: ConnectionStatus;
  controlBound: boolean;
  sandboxClosed: boolean;
  sessionId?: string;
  items: ChatItem[];
  terminal: TerminalEntry[];
  files: FileEntry[];
  activity: ActivityEntry[];
  shots: Shot[];
  droppedShots: number;
  alwaysAllow: string[];
  /** True while streamed THOUGHT tokens still belong to the latest thought item. */
  thoughtOpen?: boolean;
};
export type ReduceResult = { state: BotSession; send: OutboundFrame | null };
export const MAX_SHOTS = 30;

export function emptySession(): BotSession {
  return {
    seq: 0,
    seeded: false,
    status: "idle",
    connection: "connecting",
    controlBound: false,
    sandboxClosed: false,
    items: [],
    terminal: [],
    files: [],
    activity: [],
    shots: [],
    droppedShots: 0,
    alwaysAllow: [],
  };
}
function observe(
  state: BotSession,
  kind: ActivityEntry["kind"],
  text: string,
  at?: number,
  detail?: string,
): BotSession {
  const seq = state.seq + 1;
  return {
    ...state,
    seq,
    activity: [...state.activity, { id: `e${seq}`, kind, text, at, detail }],
  };
}
function expirePending(state: BotSession): BotSession {
  return {
    ...state,
    items: state.items.map((item) =>
      item.kind === "approval" && !item.decision
        ? { ...item, stale: true }
        : item,
    ),
  };
}
export function connectionChanged(
  state: BotSession,
  connection: ConnectionStatus,
  at?: number,
): BotSession {
  if (state.connection === connection) return state;
  let next = observe(
    { ...state, connection },
    "connection",
    connection === "connected"
      ? "Connected to control"
      : connection === "reconnecting"
        ? "Reconnecting to control"
        : connection === "connecting"
          ? "Connecting to control"
          : "Disconnected from control",
    at,
  );
  if (
    state.protocol !== 2 &&
    connection !== "connected" &&
    (state.status === "running" || state.status === "awaiting")
  )
    next = expirePending({ ...next, status: "unknown" });
  if (connection !== "connected" && state.protocol !== 2)
    next = { ...next, controlBound: false };
  return next;
}
export function appendUser(
  state: BotSession,
  text: string,
  at?: number,
): BotSession {
  const next = expirePending(state);
  const seq = state.seq + 1;
  return {
    ...next,
    seq,
    status: "running",
    seeded: true,
    thoughtOpen: false,
    items: [...next.items, { id: `e${seq}`, kind: "user", text, at }],
  };
}
export function markDecision(
  state: BotSession,
  approvalId: string,
  decision: "approve" | "deny",
  at?: number,
): BotSession {
  if (!pendingApprovals(state).some((item) => item.approvalId === approvalId))
    return state;
  const next = observe(
    state,
    "decision",
    decision === "approve" ? "Approval sent" : "Denial sent",
    at,
    "Local decision; execution outcome will follow.",
  );
  return {
    ...next,
    status: state.status === "awaiting" ? "running" : state.status,
    items: state.items.map((item) =>
      item.kind === "approval" && item.approvalId === approvalId
        ? { ...item, decision }
        : item,
    ),
  };
}
export function allowAction(state: BotSession, action: string): BotSession {
  return state.alwaysAllow.includes(action)
    ? state
    : { ...state, alwaysAllow: [...state.alwaysAllow, action] };
}
export function revokeAction(state: BotSession, action: string): BotSession {
  return {
    ...state,
    alwaysAllow: state.alwaysAllow.filter((item) => item !== action),
  };
}
export function seedHistory(
  state: BotSession,
  messages: TranscriptMessage[],
): BotSession {
  if (state.seeded) return state;
  const history: ChatItem[] = messages.map((message, index) => ({
    id: `h${index}`,
    kind: message.role === "user" ? "user" : "assistant",
    text: message.content,
  }));
  return { ...state, seeded: true, items: [...history, ...state.items] };
}
export function parseToolCall(
  payload: string,
): { command: string; output: string } | null {
  const prefix = ["run_terminal_command:", "bash:"].find((item) =>
    payload.startsWith(item),
  );
  if (!prefix) return null;
  const rest = payload.slice(prefix.length).trimStart();
  const split = rest.indexOf("\n");
  return split === -1
    ? { command: rest, output: "" }
    : { command: rest.slice(0, split), output: rest.slice(split + 1) };
}
export function pendingApprovals(
  state: BotSession,
): Extract<ChatItem, { kind: "approval" }>[] {
  return state.items.filter(
    (item): item is Extract<ChatItem, { kind: "approval" }> =>
      item.kind === "approval" && !item.decision && !item.stale,
  );
}
export function reduceFrame(
  state: BotSession,
  frame: InboundFrame,
  at?: number,
): ReduceResult {
  const done = (next: BotSession): ReduceResult => ({
    state: { ...next, thoughtOpen: false },
    send: null,
  });
  if (frame.event === "session") {
    const current = state.sandboxClosed
      ? { ...state, files: [], shots: [], terminal: [], droppedShots: 0 }
      : state;
    return done(
      observe(
        {
          ...expirePending(current),
          status: "running",
          sessionId: frame.session_id,
          controlBound: true,
          sandboxClosed: false,
        },
        "session",
        "Turn started",
        at,
      ),
    );
  }
  if (frame.event === "done" || frame.event === "closed")
    return done(
      observe(
        {
          ...expirePending(state),
          status: frame.event === "done" ? "idle" : "closed",
          ...(frame.event === "closed"
            ? { sandboxClosed: true, controlBound: false }
            : {}),
        },
        "session",
        frame.event === "done" ? "Turn finished" : "Sandbox closed",
        at,
      ),
    );
  if (frame.event === "error") {
    const next = observe(
      { ...expirePending(state), status: "error" },
      "error",
      "Turn failed",
      at,
      frame.payload,
    );
    return done({
      ...next,
      items: [
        ...next.items,
        { id: `e${next.seq}`, kind: "error", text: frame.payload, at },
      ],
    });
  }
  if (frame.event === "artifact_written") {
    const next = observe(state, "file", "File observed", at, frame.meta.path);
    return done({
      ...next,
      files: [
        ...state.files,
        {
          id: `e${next.seq}`,
          path: frame.meta.path,
          preview: frame.meta.preview,
          at,
        },
      ],
    });
  }
  if (frame.event === "approval_required") {
    const next = observe(
      state,
      "approval",
      "Approval requested",
      at,
      frame.action,
    );
    const item: ChatItem = {
      id: `e${next.seq}`,
      kind: "approval",
      approvalId: frame.approval_id,
      action: frame.action,
      detail: frame.detail,
      at,
    };
    return done({ ...next, status: "awaiting", items: [...state.items, item] });
  }
  if (frame.event !== "log") return done(state);
  if (frame.type === "SCREENSHOT_CAPTURE") {
    const seq = state.seq + 1;
    const shots = [
      ...state.shots,
      { id: `e${seq}`, src: `data:image/png;base64,${frame.payload}`, at },
    ];
    return done({
      ...state,
      seq,
      shots: shots.slice(-MAX_SHOTS),
      droppedShots: state.droppedShots + Math.max(0, shots.length - MAX_SHOTS),
    });
  }
  if (frame.type === "TOOL_CALL") {
    const terminal = parseToolCall(frame.payload);
    const next = observe(
      state,
      "tool",
      terminal ? "Terminal result" : "Tool activity",
      at,
      terminal?.command ?? frame.payload,
    );
    return done(
      terminal
        ? {
            ...next,
            terminal: [
              ...state.terminal,
              { id: `e${next.seq}`, ...terminal, at },
            ],
          }
        : next,
    );
  }
  const kind =
    frame.type === "THOUGHT"
      ? "thought"
      : frame.type === "RESULT"
        ? "assistant"
        : frame.type === "ERROR"
          ? "error"
          : frame.type === "SYSTEM"
            ? "system"
            : null;
  if (!kind || !frame.payload) return done(state);
  if (kind === "thought" && state.thoughtOpen) {
    const last = state.items.at(-1);
    if (last?.kind === "thought") {
      const items = state.items.slice();
      items[items.length - 1] = { ...last, text: last.text + frame.payload };
      return { state: { ...state, items, thoughtOpen: true }, send: null };
    }
  }
  let next = { ...state, seq: state.seq + 1 };
  if (kind === "error")
    next = observe(
      { ...expirePending(state), status: "error" },
      "error",
      "Agent reported an error",
      at,
      frame.payload,
    );
  if (kind === "assistant")
    next = observe(state, "result", "Agent replied", at);
  return {
    state: {
      ...next,
      thoughtOpen: kind === "thought",
      items: [
        ...next.items,
        { id: `e${next.seq}`, kind, text: frame.payload, at },
      ],
    },
    send: null,
  };
}
