import { apiBase } from "../api/client";
import { latestAutopilot, type AutopilotState } from "./autopilot";
import type { InboundFrame } from "../api/frames";
import {
  emptySession,
  reduceFrame,
  type BotSession,
  type BotStatus,
  type ChatItem,
  type PlanStep,
  type CaptureMetadata,
  type Shot,
  type Health,
} from "./reduce";

export type ServerMessage = {
  id: string;
  role: "user" | "assistant";
  content: string;
  seq: number;
  ordinal: number;
  occurred_at: string | null;
};
export type ServerApproval = {
  id: string;
  action: string;
  detail: string;
  revision: number;
  created_at: string;
  action_id?: string;
  policy_scope?: string;
  expires_at?: string;
};
export type { EventEnvelope as ServerEvent } from "../api/events.generated";
import type { EventEnvelope as ServerEvent } from "../api/events.generated";
export type RetainedCapture = { capture_id: string; url: string; capture: CaptureMetadata; created_at: string; expires_at?: string | null; storage_sequence?: number };
export function retainedShot(c: RetainedCapture): Shot {
  return { id: c.capture_id, src: `${apiBase()}${c.url}`, capture: c.capture, at: Date.parse(c.created_at), expiresAt: c.expires_at, storageSequence: c.storage_sequence };
}
export type Snapshot = {
  captures?: RetainedCapture[];
  captures_revision?: number;
  tools_revision?: number;
  autopilot?: AutopilotState;
  health?: Health | null;
  schema_version: 2;
  bot_id: string;
  snapshot_seq: number;
  computer: { id: string; status: string } | null;
  run: { id: string; status: string; session_id?: string } | null;
  messages: ServerMessage[];
  messages_before: number | null;
  events: ServerEvent[];
  pending_approvals: ServerApproval[];
  observations_truncated: boolean;
  actions?: {
    id: string;
    operation: string;
    status: string;
    step_id: string | null;
    result: Record<string, unknown> | null;
    approval_id: string;
    detail: string;
    approval_status: string;
    revision: number;
    decided_by: string | null;
    decision_source?: string | null;
    autopilot_revision?: number | null;
    created_at: string;
    policy_scope: string | null;
    expires_at: string;
  }[];
  plan?: PlanStep[] | null;
};

function runStatus(status?: string): BotStatus {
  if (status === "awaiting_approval") return "awaiting";
  if (status === "stopping") return "stopping";
  if (status === "preparing" || status === "running") return "running";
  if (status === "interrupted") return "unknown";
  if (status === "failed") return "error";
  return "idle";
}

function legacyObservation(
  state: BotSession,
  event: ServerEvent,
  frame: InboundFrame,
): BotSession {
  const next = reduceFrame(
    { ...state, alwaysAllow: [] },
    frame,
    Date.parse(event.occurred_at),
  ).state;
  // Identity comes from the server, never from how many frames this tab saw.
  for (const field of [
    "items",
    "files",
    "terminal",
    "shots",
    "activity",
  ] as const) {
    const oldIds = new Set(state[field].map((item) => item.id));
    (next[field] as { id: string; order?: number }[]) = next[field].map(
      (item, index) =>
        oldIds.has(item.id)
          ? item
          : {
              ...item,
              id: `${event.event_id}:${field}:${index}`,
              order: event.seq,
            },
    );
  }
  return next;
}

export function applyEvent(state: BotSession, event: ServerEvent): BotSession {
  if (event.seq <= (state.serverSeq ?? 0)) return state;
  let next = { ...state, protocol: 2 as const, serverSeq: event.seq };
  const data = event.data;
  const at = Date.parse(event.occurred_at);
  if (event.type === "bot.autopilot.changed") {
    next.autopilot = latestAutopilot(next.autopilot, data as AutopilotState);
  } else if (event.type === "message.created") {
    const item: ChatItem = {
      id: String(data.id),
      kind: data.role === "user" ? "user" : "assistant",
      text: String(data.content),
      at,
      order: event.seq,
    };
    if (!next.items.some((existing) => existing.id === item.id))
      next.items = [...next.items, item];
  } else if (event.type === "observation") {
    if (data.legacy_only) next.thoughtOpen = false;
    else
      next = legacyObservation(
        next,
        event,
        data.frame as InboundFrame,
      ) as typeof next;
  } else if (event.type === "captures.changed") {
    next.capturesInvalidation = event.seq;
    const removed = new Set((data.removed_ids as string[]) ?? []);
    next.removedCaptureIds = [...new Set([...(next.removedCaptureIds ?? []), ...removed])].slice(-500);
    next.shots = next.shots.filter(shot => !removed.has(shot.id));
    next.capturesRevision = Number(data.revision);
  } else if (event.type === "capture.available") {
    next.capturesRevision = Number(data.revision ?? next.capturesRevision ?? 0);
    next.shots = [
      ...next.shots,
      {
        id: String(data.capture_id),
        src: `${apiBase()}${data.url}`,
        at,
        order: event.seq,
        capture: data.capture as CaptureMetadata | undefined,
        expiresAt: data.expires_at as string | null | undefined,
        storageSequence: data.storage_sequence as number | undefined,
      },
    ].slice(-30);
  } else if (event.type === "files.changed" || event.type === "file.uploaded") {
    next.filesRevision = event.seq;
  } else if (event.type === "computer.health") {
    next.health = data as unknown as Health;
  } else if (event.type === "approval.required") {
    next.items = [
      ...next.items.filter(
        (item) => item.id !== `approval_${data.approval_id}`,
      ),
      {
        id: `approval_${data.approval_id}`,
        kind: "approval",
        approvalId: String(data.approval_id),
        action: String(data.action),
        detail: String(data.detail),
        revision: Number(data.revision),
        actionId: event.action_id ?? undefined,
        policyScope: data.policy_scope ? String(data.policy_scope) : undefined,
        expiresAt: data.expires_at ? String(data.expires_at) : undefined,
        at,
        order: event.seq,
      },
    ];
    next.status = "awaiting";
  } else if (event.type === "approval.resolved") {
    // Immediate decisions have no approval.required event or pending notification.
    if (data.decision_source === "autopilot" && !next.items.some(
      (item) => item.kind === "approval" && item.approvalId === data.approval_id,
    )) {
      next.items = [...next.items, {
        id: `approval_${data.approval_id}`, kind: "approval",
        approvalId: String(data.approval_id), actionId: event.action_id ?? undefined,
        action: String(data.action ?? "action"), detail: String(data.detail ?? ""),
        at, order: event.seq,
      }];
    }
    next.items = next.items.map((item) =>
      item.kind === "approval" && item.approvalId === data.approval_id
        ? {
            ...item,
            revision: Number(data.revision),
            acknowledged: true,
            decisionSource: data.decision_source ? String(data.decision_source) : item.decisionSource,
            autopilotRevision: data.autopilot_revision != null ? Number(data.autopilot_revision) : item.autopilotRevision,
            decidedBy: data.decided_by ? String(data.decided_by) : item.decidedBy,
            decisionReason: data.reason ? String(data.reason) : undefined,
            decision:
              data.status === "approved"
                ? "approve"
                : data.status === "denied"
                  ? "deny"
                  : undefined,
            stale: data.status !== "approved" && data.status !== "denied",
          }
        : item,
    );
    if (next.status === "awaiting") next.status = "running";
  } else if (
    event.type === "action.started" ||
    event.type === "action.completed" ||
    event.type === "action.failed"
  ) {
    const actionId = event.action_id ?? event.event_id;
    const old = next.actions?.[actionId];
    const status =
      event.type === "action.started"
        ? "executing"
        : data.outcome_unknown
          ? "outcome_unknown"
          : data.cancelled
            ? "cancelled"
            : event.type === "action.completed"
              ? "completed"
              : "failed";
    const outcome =
      status === "executing" ? "Executing action" : actionOutcome(data);
    const action = {
      decisionSource: data.decision_source ? String(data.decision_source) : old?.decisionSource,
      autopilotRevision: data.autopilot_revision != null ? Number(data.autopilot_revision) : old?.autopilotRevision,
      decidedBy: data.decided_by ? String(data.decided_by) : old?.decidedBy,
      operation: String(data.operation ?? old?.operation ?? "action"),
      detail: String(data.detail ?? old?.detail ?? ""),
      status,
      outcome,
      stepId: data.step_id ? String(data.step_id) : old?.stepId,
    };
    next.actions = { ...next.actions, [actionId]: action };
    next.items = next.items.map((item) =>
      item.kind === "approval" &&
      (item.actionId === actionId || item.approvalId === data.approval_id)
        ? { ...item, actionId, actionStatus: status, resultText: outcome }
        : item,
    );
    if (action.operation === "bash" && status !== "executing") {
      next.terminal = [
        ...next.terminal.filter((item) => item.id !== actionId),
        {
          id: actionId,
          command: action.detail,
          output: [data.stdout, data.stderr].filter(Boolean).join("\n"),
          outcome,
          at,
          order: event.seq,
        },
      ];
    }
  } else if (event.type === "plan.updated") {
    next.plan = Array.isArray(data.steps)
      ? (data.steps as PlanStep[])
      : undefined;
  } else if (event.type === "run.started") {
    next.plan = undefined;
    const communicationOnly = data.run_mode === "communication";
    if (!communicationOnly && state.sessionId !== event.session_id) {
      next.files = [];
      next.shots = [];
      next.terminal = [];
      next.droppedShots = 0;
    }
    next.runId = event.run_id ?? undefined;
    if (!communicationOnly) {
      next.sessionId = event.session_id ?? undefined;
      next.sandboxClosed = false;
      next.controlBound = true;
    }
    next.status = "running";
  } else if (event.type === "run.stopping") {
    next.status = "stopping";
  } else if (event.type === "run.finished") {
    next.status = runStatus(String(data.status));
    next.items = next.items.map((item) =>
      item.kind === "approval" && !item.decision
        ? { ...item, stale: true }
        : item,
    );
    if (data.outcome)
      next.items = [
        ...next.items,
        {
          id: event.event_id,
          kind: next.status === "error" ? "error" : "system",
          text: String(data.outcome),
          at,
          order: event.seq,
        },
      ];
  } else if (event.type.startsWith("session.")) {
    if (data.status === "running" && event.session_id !== next.sessionId) {
      // An explicitly created connection is idle until its own run starts.
      next.status = "idle";
      next.runId = undefined;
    }
    next.sessionId = event.session_id ?? undefined;
    next.computerStatus = String(data.status);
    next.controlBound = data.status !== "closed";
    next.sandboxClosed = data.status === "closed";
    if (next.sandboxClosed) next.status = "closed";
  }
  if (event.type === "bot.tools.updated") next.toolsRevision = Number(data.tools_revision);
  if (event.type !== "observation") next.thoughtOpen = false;
  if (event.type !== "observation" && event.type !== "capture.available") {
    next.activity = [
      ...next.activity,
      {
        id: event.event_id,
        kind: event.type.startsWith("approval")
          ? ("approval" as const)
          : event.type === "action.failed"
            ? ("error" as const)
            : event.type.startsWith("action.")
              ? ("tool" as const)
              : ("session" as const),
        text: event.type === "capture.skipped" ? `Screenshot not retained: ${data.reason ?? "Storage unavailable"}` : event.type === "bot.autopilot.changed"
          ? `Autopilot ${data.enabled ? "on" : "off"}`
          : event.type === "approval.resolved" && data.decision_source === "autopilot"
            ? data.status === "approved" ? "Auto-approved by Autopilot" : String(data.reason ?? "Autopilot approval cancelled")
          : event.type.startsWith("action.")
          ? `${data.operation ?? "Action"}: ${event.type === "action.started" ? "executing" : actionOutcome(data)}`
          : event.type === "run.finished" && Number(data.failed_actions) > 0
            ? `Run ${data.status}; ${data.failed_actions} failed or cancelled action(s)`
            : event.type.replaceAll(".", " "),
        detail: event.type === "bot.autopilot.changed"
          ? `Changed by ${data.changed_by}; revision ${data.revision}`
          : data.decision_source === "autopilot"
            ? `Auto-approved by Autopilot · owner ${data.decided_by} · revision ${data.autopilot_revision}`
          : event.type.startsWith("action.")
          ? [
              data.detail,
              data.stderr,
              data.policy_id
                ? `Authorized by rule ${data.policy_id} v${data.policy_version}`
                : undefined,
            ]
              .filter(Boolean)
              .join("\n")
          : undefined,
        at,
      },
    ].slice(-500);
  }
  return next;
}

function actionOutcome(data: Record<string, unknown>): string {
  const outcome = data.outcome_unknown
    ? "Outcome unknown"
    : data.cancelled
      ? "Action cancelled"
      : data.timed_out
        ? "Command timed out"
        : typeof data.exit_code === "number"
          ? `Exit ${data.exit_code}`
          : data.command_id
            ? "Exit status unknown"
            : data.ok
              ? "Action completed"
              : "Action failed";
  return (
    outcome +
    (data.stdout_truncated || data.stderr_truncated
      ? " · Output truncated"
      : "")
  );
}

export function mergeMessages(
  state: BotSession,
  messages: ServerMessage[],
): BotSession {
  const byId = new Map(state.items.map((item) => [item.id, item]));
  for (const m of messages)
    byId.set(m.id, {
      id: m.id,
      kind: m.role,
      text: m.content,
      at: m.occurred_at ? Date.parse(m.occurred_at) : undefined,
      order: m.seq || -1_000_000_000 + m.ordinal,
    });
  return {
    ...state,
    items: [...byId.values()].sort((a, b) => (a.order ?? 0) - (b.order ?? 0)),
  };
}

export function applySnapshot(
  previous: BotSession,
  snapshot: Snapshot,
): BotSession {
  const currentRun = snapshot.run?.session_id && snapshot.run.session_id !== snapshot.computer?.id
    ? null : snapshot.run;
  let state: BotSession = {
    ...emptySession(),
    protocol: 2,
    seeded: true,
    connection: previous.connection,
  };
  for (const event of snapshot.events) state = applyEvent(state, event);
  if (snapshot.captures) state.shots = [...snapshot.captures].reverse().map(retainedShot).filter(s => !s.expiresAt || Date.parse(s.expiresAt) > Date.now());
  state.capturesRevision = snapshot.captures_revision;
  state.toolsRevision = snapshot.tools_revision ?? state.toolsRevision;
  // Messages have their own durable projection, independent of event retention.
  state.items = state.items.filter(
    (item) => item.kind !== "user" && item.kind !== "assistant",
  );
  state = mergeMessages(state, snapshot.messages);
  for (const action of snapshot.actions ?? []) {
    const resultText =
      action.status === "executing"
        ? "Executing action"
        : action.result
          ? actionOutcome(action.result)
          : undefined;
    state.actions = {
      ...state.actions,
      [action.id]: {
        decisionSource: action.decision_source ?? undefined,
        autopilotRevision: action.autopilot_revision ?? undefined,
        decidedBy: action.decided_by ?? undefined,
        operation: action.operation,
        detail: action.detail,
        status: action.status,
        stepId: action.step_id ?? undefined,
        outcome: resultText,
      },
    };
    const existing = state.items.find(
      (item) =>
        item.kind === "approval" && item.approvalId === action.approval_id,
    );
    if (
      existing ||
      !(
        action.decided_by?.startsWith("policy:") ||
        action.decided_by?.startsWith("system:")
      )
    ) {
      const item: ChatItem = {
        id: `approval_${action.approval_id}`,
        kind: "approval",
        approvalId: action.approval_id,
        decisionSource: action.decision_source ?? undefined,
        autopilotRevision: action.autopilot_revision ?? undefined,
        decidedBy: action.decided_by ?? undefined,
        decisionReason: action.decision_source === "autopilot" && action.approval_status === "cancelled"
          ? "Autopilot authorization cancelled before execution" : undefined,
        action: action.operation,
        detail: action.detail,
        revision: action.revision,
        actionId: action.id,
        at: Date.parse(action.created_at),
        order: existing?.order ?? snapshot.snapshot_seq,
        acknowledged: action.approval_status !== "pending",
        decision:
          action.approval_status === "approved"
            ? "approve"
            : action.approval_status === "denied"
              ? "deny"
              : undefined,
        stale: ["expired", "cancelled"].includes(action.approval_status),
        policyScope: action.policy_scope ?? undefined,
        expiresAt: action.expires_at,
        actionStatus: resultText ? action.status : undefined,
        resultText,
      };
      state.items = existing
        ? state.items.map((old) => (old.id === existing.id ? item : old))
        : [...state.items, item];
    }
    if (action.operation === "bash" && action.result) {
      state.terminal = [
        ...state.terminal.filter((item) => item.id !== action.id),
        {
          id: action.id,
          command: action.detail,
          output: [action.result.stdout, action.result.stderr]
            .filter(Boolean)
            .join("\n"),
          outcome: resultText,
          at: Date.parse(String(action.result.ended_at ?? action.created_at)),
        },
      ];
    }
  }
  if (snapshot.plan !== undefined) state.plan = snapshot.plan ?? undefined;
  for (const approval of snapshot.pending_approvals) {
    if (
      !state.items.some(
        (item) => item.kind === "approval" && item.approvalId === approval.id,
      )
    ) {
      state.items.push({
        id: `approval_${approval.id}`,
        kind: "approval",
        approvalId: approval.id,
        action: approval.action,
        detail: approval.detail,
        revision: approval.revision,
        actionId: approval.action_id,
        policyScope: approval.policy_scope,
        expiresAt: approval.expires_at,
        at: Date.parse(approval.created_at),
        order: snapshot.snapshot_seq,
      });
    }
  }
  return {
    ...state,
    serverSeq: snapshot.snapshot_seq,
    autopilot: latestAutopilot(previous.autopilot, latestAutopilot(state.autopilot, snapshot.autopilot)),
    sessionId: snapshot.computer?.id,
    computerStatus: snapshot.computer?.status,
    health: snapshot.health ?? state.health,
    runId: currentRun?.id,
    status:
      snapshot.computer?.status === "closed"
        ? "closed"
        : runStatus(currentRun?.status),
    controlBound: !!snapshot.computer && snapshot.computer.status !== "closed",
    sandboxClosed: snapshot.computer?.status === "closed",
    messagesBefore: snapshot.messages_before,
    observationsTruncated: snapshot.observations_truncated,
    commandError: previous.commandError,
    submitting: previous.submitting,
    submittingApprovalId: previous.submittingApprovalId,
  };
}
