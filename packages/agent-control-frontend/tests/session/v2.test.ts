import { describe, expect, it } from "vitest";
import {
  applyEvent,
  applySnapshot,
  type Snapshot,
  type ServerEvent,
} from "../../src/session/v2";
import { connectionChanged, emptySession, pendingApprovals } from "../../src/session/reduce";

it("keeps the existing computer attached during a communication-only run", () => {
  const state = { ...emptySession(), sessionId: "computer_existing", computerStatus: "running", controlBound: true };
  const next = applyEvent(state, { ...event(1, "run.started", { status: "preparing", run_mode: "communication" }), session_id: null });
  expect(next.sessionId).toBe("computer_existing");
  expect(next.computerStatus).toBe("running");
  expect(next.status).toBe("running");
  expect(next.controlBound).toBe(true);
});

it("keeps approval, execution, and command failure separate and deduplicates results", () => {
  const events = [
    event(1, "approval.required", {
      approval_id: "ap",
      action: "bash",
      detail: "exit 7",
      revision: 1,
    }),
    event(2, "approval.resolved", {
      approval_id: "ap",
      status: "approved",
      revision: 2,
    }),
    event(3, "action.started", {
      approval_id: "ap",
      operation: "bash",
      detail: "exit 7",
    }),
    event(4, "action.failed", {
      approval_id: "ap",
      operation: "bash",
      command_id: "cmd",
      exit_code: 7,
      stdout: "",
      stderr: "failed",
      ok: false,
      stdout_truncated: true,
    }),
  ].map((value) => ({ ...value, action_id: "action_1" }));
  let state = applyEvent(emptySession(), events[0]!);
  state = applyEvent(state, events[1]!);
  expect(state.items[0]).toMatchObject({
    decision: "approve",
    acknowledged: true,
  });
  expect(state.actions).toBeUndefined();
  state = applyEvent(state, events[2]!);
  expect(state.items[0]).toMatchObject({ actionStatus: "executing" });
  state = applyEvent(state, events[3]!);
  expect(state.items[0]).toMatchObject({
    actionStatus: "failed",
    resultText: "Exit 7 · Output truncated",
  });
  expect(state.terminal[0]).toMatchObject({
    command: "exit 7",
    output: "failed",
  });
  expect(applyEvent(state, events[3]!)).toBe(state);
  const legacy = applyEvent(
    state,
    event(5, "observation", {
      legacy_only: true,
      frame: {
        event: "log",
        type: "TOOL_CALL",
        payload: "bash: exit 7\nexit 7",
      },
    }),
  );
  expect(legacy.terminal).toEqual(state.terminal);
  const replayed = applySnapshot(emptySession(), {
    ...snapshot,
    snapshot_seq: 4,
    events,
    pending_approvals: [],
    messages: [],
    run: { id: "run_1", status: "completed" },
  });
  expect(replayed.terminal).toEqual(state.terminal);
  expect(replayed.items[0]).toMatchObject({ actionStatus: "failed" });
});

it("does not infer progress or cloud publication from a successful action", () => {
  let state = applyEvent(
    emptySession(),
    event(1, "action.completed", { operation: "bash", ok: true, exit_code: 0 }),
  );
  expect(state.plan).toBeUndefined();
  expect(JSON.stringify(state)).not.toMatch(/published|uploaded/i);
  state = applyEvent(
    state,
    event(2, "plan.updated", {
      steps: [{ id: "verify", title: "Verify report", status: "running" }],
    }),
  );
  expect(state.plan).toEqual([
    { id: "verify", title: "Verify report", status: "running" },
  ]);
});

it("recovers the latest action and explicit plan when their events have expired", () => {
  const state = applySnapshot(emptySession(), {
    ...snapshot,
    pending_approvals: [],
    messages: [],
    events: [],
    run: { id: "run_1", status: "completed" },
    actions: [
      {
        id: "action_1",
        operation: "bash",
        status: "failed",
        step_id: "verify",
        result: {
          ok: false,
          exit_code: 7,
          stderr: "Invalid report",
          ended_at: "2026-10-07T12:00:02Z",
        },
        approval_id: "ap",
        detail: "verify report",
        approval_status: "approved",
        revision: 2,
        decided_by: "user_1",
        created_at: "2026-10-07T12:00:00Z",
        policy_scope: null,
        expires_at: "2026-10-07T12:02:00Z",
      },
    ],
    plan: [{ id: "verify", title: "Verify report", status: "failed" }],
  });
  expect(state.items[0]).toMatchObject({
    decision: "approve",
    acknowledged: true,
    actionStatus: "failed",
    resultText: "Exit 7",
  });
  expect(state.terminal[0]).toMatchObject({
    command: "verify report",
    output: "Invalid report",
  });
  expect(state.plan?.[0].status).toBe("failed");
  expect(state.status).toBe("idle");
});

const snapshot: Snapshot = {
  schema_version: 2,
  bot_id: "bot",
  snapshot_seq: 5,
  computer: { id: "computer_1", status: "running" },
  run: { id: "run_1", status: "awaiting_approval" },
  messages: [
    {
      id: "old_message",
      role: "user",
      content: "Old history",
      seq: 0,
      ordinal: 1,
      occurred_at: null,
    },
  ],
  messages_before: null,
  events: [],
  observations_truncated: true,
  pending_approvals: [
    {
      id: "ap",
      action: "bash",
      detail: "pwd",
      revision: 1,
      created_at: "2026-10-07T12:00:00Z",
    },
  ],
};
const event = (
  seq: number,
  type: string,
  data: Record<string, unknown>,
): ServerEvent => ({
  schema_version: 2,
  event_id: `event_${seq}`,
  bot_id: "bot",
  seq,
  session_id: "computer_1",
  run_id: "run_1",
  occurred_at: "2026-10-07T12:00:00Z",
  type,
  data,
});

describe("durable server presentation", () => {
  it("keeps recovery required until a new computer connection replaces the failed one", () => {
    const interrupted: Snapshot = {
      ...snapshot,
      pending_approvals: [],
      computer: { id: "computer_1", status: "failed" },
      run: { id: "run_1", status: "interrupted", session_id: "computer_1" },
    };
    const failed = applySnapshot(emptySession(), interrupted);
    expect(failed.status).toBe("unknown");
    const seq = (failed.serverSeq ?? 0) + 1;
    const healthy = applyEvent(failed, event(seq, "computer.health", { health: "healthy" }));
    expect(healthy.status).toBe("unknown");
    expect(healthy.computerStatus).toBe("failed");

    const closed = applyEvent(healthy, event(seq + 1, "session.closed", { status: "closed" }));
    const reconnected = applyEvent(closed, {
      ...event(seq + 2, "session.bound", { status: "running" }),
      session_id: "computer_2", run_id: null,
    });
    expect(reconnected.status).toBe("idle");
    expect(reconnected.runId).toBeUndefined();
    const refreshed = applySnapshot(reconnected, {
      ...interrupted, computer: { id: "computer_2", status: "running" },
    });
    expect(refreshed.status).toBe("idle");
    expect(refreshed.runId).toBeUndefined();
  });

  it("restores an approval absent from retained events and preserves unknown history times", () => {
    const restored = applySnapshot(emptySession(), snapshot);
    expect(restored.items[0].at).toBeUndefined();
    expect(pendingApprovals(restored)[0].approvalId).toBe("ap");
    expect(restored.status).toBe("awaiting");
    const disconnected = connectionChanged(restored, "reconnecting");
    expect(disconnected.status).toBe("awaiting");
    expect(pendingApprovals(disconnected)).toHaveLength(1);
  });
  it("deduplicates replay, acknowledges server decisions, and keeps stable message IDs", () => {
    let state = applySnapshot(emptySession(), snapshot);
    const decision = event(6, "approval.resolved", {
      approval_id: "ap",
      status: "approved",
      revision: 2,
    });
    state = applyEvent(state, decision);
    expect(applyEvent(state, decision)).toBe(state);
    expect(state.items.at(-1)).toMatchObject({
      acknowledged: true,
      decision: "approve",
    });
    const message = event(7, "message.created", {
      id: "message_2",
      role: "assistant",
      content: "Done",
    });
    state = applyEvent(applyEvent(state, message), message);
    expect(state.items.filter((item) => item.id === "message_2")).toHaveLength(
      1,
    );
  });
  it("joins streamed thought observations and rebuilds the same item from a snapshot", () => {
    const thought = (seq: number, payload: string) =>
      event(seq, "observation", {
        frame: { event: "log", type: "THOUGHT", payload },
      });
    const events = [thought(1, "Let"), thought(2, " me"), thought(3, " check")];
    let state = emptySession();
    for (const item of events) state = applyEvent(state, item);
    const thoughts = state.items.filter((item) => item.kind === "thought");
    expect(thoughts).toHaveLength(1);
    expect(thoughts[0]).toMatchObject({
      id: "event_1:items:0",
      text: "Let me check",
      order: 1,
    });

    state = applyEvent(
      state,
      event(4, "observation", {
        frame: {
          event: "log",
          type: "TOOL_CALL",
          payload: "bash: ls\nfile.txt",
        },
      }),
    );
    state = applyEvent(state, thought(5, "later"));
    expect(
      state.items
        .filter((item) => item.kind === "thought")
        .map((item) => item.text),
    ).toEqual(["Let me check", "later"]);

    const rebuilt = applySnapshot(emptySession(), {
      ...snapshot,
      snapshot_seq: 3,
      messages: [],
      pending_approvals: [],
      observations_truncated: false,
      run: { id: "run_1", status: "running" },
      events,
    });
    expect(rebuilt.items.filter((item) => item.kind === "thought")).toEqual(
      thoughts,
    );
  });
  it("a replacement computer clears old observations and stopped runs remain non-busy", () => {
    let state = applySnapshot(emptySession(), snapshot);
    state = applyEvent(
      state,
      event(6, "observation", {
        frame: {
          event: "artifact_written",
          meta: { path: "/workspace/old", preview: "old" },
        },
      }),
    );
    expect(state.files).toHaveLength(1);
    state = applyEvent(state, {
      ...event(7, "run.started", {}),
      session_id: "computer_2",
    });
    expect(state.files).toHaveLength(0);
    state = applyEvent(state, event(8, "run.stopping", {}));
    expect(state.status).toBe("stopping");
    state = applyEvent(
      state,
      event(9, "run.finished", { status: "cancelled", outcome: "Stopped" }),
    );
    expect(state.status).toBe("idle");
  });
});


it("uses retained captures instead of resurrecting expired event URLs", () => {
  const previous = emptySession();
  const state = applySnapshot(previous, {
    schema_version: 2, bot_id: "bot", snapshot_seq: 1,
    computer: null, run: null, messages: [], messages_before: null,
    pending_approvals: [], observations_truncated: false,
    events: [{ schema_version: 2, event_id: "capture-event", seq: 1,
      bot_id: "bot", session_id: null, run_id: null, occurred_at: new Date().toISOString(),
      type: "capture.available", data: { capture_id: "expired", url: "/expired.png" } }],
    captures: [], captures_revision: 2,
  });
  expect(state.shots).toEqual([]);
  expect(state.serverSeq).toBe(1);
});

it("removes capture URLs on retention invalidation without losing messages", () => {
  const state = { ...emptySession(), shots: [{ id: "gone", src: "/gone.png" }, { id: "keep", src: "/keep.png" }] };
  const next = applyEvent(state, { schema_version: 2, event_id: "prune", seq: 1,
    bot_id: "bot", session_id: null, run_id: null, occurred_at: new Date().toISOString(),
    type: "captures.changed", data: { revision: 3, removed_ids: ["gone"] } });
  expect(next.shots.map(s => s.id)).toEqual(["keep"]);
  expect(next.items).toEqual(state.items);
});
