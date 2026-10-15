import { expect, it } from "vitest";
import { latestAutopilot, type AutopilotState } from "../../src/session/autopilot";
import { emptySession, pendingApprovals } from "../../src/session/reduce";
import { applyEvent, applySnapshot, type ServerEvent, type Snapshot } from "../../src/session/v2";
import { useSessionStore } from "../../src/session/store";

const mode = (revision: number, enabled: boolean): AutopilotState => ({
  bot_id: "bot", enabled, revision, changed_by: "owner", changed_at: "2026-10-07T12:00:00Z",
});
const event = (seq: number, type: string, data: Record<string, unknown>): ServerEvent => ({
  schema_version: 2, bot_id: "bot", run_id: "run", session_id: "computer", action_id: "action",
  event_id: `event_${seq}`, seq, occurred_at: "2026-10-07T12:00:00Z", type, data,
});
const snapshot: Snapshot = {
  schema_version: 2, bot_id: "bot", snapshot_seq: 2, computer: null, run: null,
  messages: [], messages_before: null, events: [], pending_approvals: [], observations_truncated: false,
};

it("ignores stale receipts, settings reads, events and snapshots", () => {
  const off = mode(2, false);
  const on = mode(1, true);
  expect(latestAutopilot(off, on)).toBe(off);
  useSessionStore.getState().setAutopilot("bot", off);
  useSessionStore.getState().setAutopilot("bot", on);
  let state = useSessionStore.getState().sessions.bot!;
  expect(state.autopilot).toBe(off);
  state = applyEvent(state, event(1, "bot.autopilot.changed", on));
  expect(state.autopilot).toBe(off);
  state = applySnapshot(state, { ...snapshot, autopilot: on, events: [event(1, "bot.autopilot.changed", on)] });
  expect(state.autopilot).toBe(off);
  expect(applyEvent(state, event(3, "bot.autopilot.changed", mode(3, true))).autopilot?.enabled).toBe(true);
});

it("shows immediate Autopilot approval without a pending card or a success result", () => {
  let state = applyEvent(emptySession(), event(1, "approval.resolved", {
    approval_id: "approval", action: "bash", detail: "exit 7", revision: 2, status: "approved",
    decision_source: "autopilot", autopilot_revision: 1, decided_by: "owner",
  }));
  expect(pendingApprovals(state)).toEqual([]);
  expect(state.items[0]).toMatchObject({ decision: "approve", decisionSource: "autopilot", autopilotRevision: 1, decidedBy: "owner" });
  expect(state.items[0]).not.toHaveProperty("resultText");
  expect(state.activity[0]?.text).toBe("Auto-approved by Autopilot");
  state = applyEvent(state, event(2, "action.started", { operation: "bash", approval_id: "approval", decision_source: "autopilot", autopilot_revision: 1, decided_by: "owner" }));
  state = applyEvent(state, event(3, "action.failed", { operation: "bash", approval_id: "approval", exit_code: 7, ok: false }));
  expect(state.items[0]).toMatchObject({ resultText: "Exit 7", decisionSource: "autopilot" });
  expect(state.actions?.action?.decisionSource).toBe("autopilot");
});

it("rebuilds decision attribution after event retention and keeps revocations inactive", () => {
  const state = applySnapshot(emptySession(), { ...snapshot, autopilot: mode(2, false), actions: [{
    id: "action", operation: "bash", status: "cancelled", step_id: null, result: { ok: false, cancelled: true },
    approval_id: "approval", detail: "hello", approval_status: "cancelled", revision: 3,
    decided_by: "owner", decision_source: "autopilot", autopilot_revision: 1,
    created_at: "2026-10-07T12:00:00Z", policy_scope: null, expires_at: "2026-10-07T12:05:00Z",
  }] });
  expect(state.items[0]).toMatchObject({ decisionSource: "autopilot", stale: true, resultText: "Action cancelled", autopilotRevision: 1 });
  expect(pendingApprovals(state)).toEqual([]);
});
