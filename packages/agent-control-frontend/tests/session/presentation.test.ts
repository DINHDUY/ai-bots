import { describe, expect, it } from "vitest";
import { waitFor } from "@testing-library/react";
import {
  appendUser,
  connectionChanged,
  emptySession,
  markDecision,
  MAX_SHOTS,
  pendingApprovals,
  reduceFrame,
  seedHistory,
} from "../../src/session/reduce";
import { observedFiles, protectedFile } from "../../src/session/selectors";
import { resetWorkspaceUi, useWorkspaceUi } from "../../src/session/workspaceUiStore";
import { resetSessions, sessionFor, useSessionStore } from "../../src/session/store";
import { FakeWebSocket } from "../support/fakeSocket";

describe("session presentation", () => {
  it("keeps session identity separate from connectivity and expires interrupted approvals", () => {
    let state = connectionChanged(emptySession(), "connected", 1);
    state = reduceFrame(
      state,
      { event: "session", session_id: "real-session" },
      2,
    ).state;
    state = reduceFrame(
      state,
      {
        event: "approval_required",
        approval_id: "ap",
        action: "bash",
        detail: "pwd",
      },
      3,
    ).state;
    state = connectionChanged(state, "reconnecting", 4);
    expect(state.sessionId).toBe("real-session");
    expect(state.controlBound).toBe(false);
    expect(state.status).toBe("unknown");
    expect(pendingApprovals(state)).toHaveLength(0);
    state = connectionChanged(state, "connected", 5);
    expect(state.status).toBe("unknown");
    expect(state.controlBound).toBe(false);
    expect(markDecision(state, "ap", "approve", 6)).toBe(state);
    expect(state.activity.at(-1)).toMatchObject({ at: 5, kind: "connection" });
  });
  it("records local decisions without claiming execution success and rejects repeats", () => {
    let state = reduceFrame(
      emptySession(),
      {
        event: "approval_required",
        approval_id: "ap",
        action: "bash",
        detail: "pwd",
      },
      10,
    ).state;
    state = markDecision(state, "ap", "deny", 11);
    expect(state.status).toBe("running");
    expect(state.activity.at(-1)).toMatchObject({
      text: "Denial sent",
      at: 11,
    });
    expect(markDecision(state, "ap", "deny", 12)).toBe(state);
    expect(reduceFrame(state, { event: "done" }, 13).state.status).toBe("idle");
  });
  it("bounds screenshots and preserves the newest capture without fabricated history times", () => {
    let state = seedHistory(emptySession(), [
      { role: "assistant", content: "Old result" },
    ]);
    expect(state.items[0].at).toBeUndefined();
    for (let i = 0; i < MAX_SHOTS + 7; i++)
      state = reduceFrame(
        state,
        { event: "log", type: "SCREENSHOT_CAPTURE", payload: String(i) },
        i,
      ).state;
    expect(state.shots).toHaveLength(MAX_SHOTS);
    expect(state.droppedShots).toBe(7);
    expect(state.shots[0].at).toBe(7);
    expect(state.shots.at(-1)?.src).toContain(String(MAX_SHOTS + 6));
  });
  it("keeps a latest-per-path view without losing artifact history or hiding different original paths", () => {
    let state = emptySession();
    for (const [path, preview] of [
      ["/workspace/a.json", "partial {"],
      ["/workspace/b.txt", "second"],
      ["/workspace/a.json", "updated"],
    ])
      state = reduceFrame(
        state,
        { event: "artifact_written", meta: { path, preview } },
        50,
      ).state;
    expect(state.files).toHaveLength(3);
    expect(observedFiles(state.files).map((file) => file.preview)).toEqual([
      "updated",
      "second",
    ]);
    expect(protectedFile("C:\\workspace\\azure.env")).toBe(true);
    expect(protectedFile("/workspace/.env.production")).toBe(true);
    expect(protectedFile("/workspace/report.json")).toBe(false);
  });
  it("never timestamps old history or consults a clock inside reduction", () => {
    const initial = appendUser(emptySession(), "Hello", 123);
    const frame = { event: "log", type: "RESULT", payload: "Done" } as const;
    expect(reduceFrame(initial, frame, 456)).toEqual(
      reduceFrame(initial, frame, 456),
    );
    expect(initial.items[0].at).toBe(123);
  });
  it("keeps closed observations historical until a new sandbox turn starts", () => {
    let state = reduceFrame(
      emptySession(),
      {
        event: "artifact_written",
        meta: { path: "/workspace/old.txt", preview: "old" },
      },
      1,
    ).state;
    state = reduceFrame(
      state,
      { event: "log", type: "SCREENSHOT_CAPTURE", payload: "old-image" },
      2,
    ).state;
    state = reduceFrame(state, { event: "closed" }, 3).state;
    expect(state.sandboxClosed).toBe(true);
    expect(state.files).toHaveLength(1);
    state = appendUser(state, "Start a new task", 4);
    expect(state.sandboxClosed).toBe(true);
    state = reduceFrame(
      state,
      { event: "session", session_id: "same-bot" },
      5,
    ).state;
    expect(state.sandboxClosed).toBe(false);
    expect(state.files).toHaveLength(0);
    expect(state.shots).toHaveLength(0);
    expect(state.items.at(-1)).toMatchObject({ text: "Start a new task" });
  });
  it("clears drafts and selection on sign-out", () => {
    useWorkspaceUi
      .getState()
      .patch("one", { draft: "first", filePath: "/workspace/a" });
    useWorkspaceUi.getState().patch("two", { draft: "second" });
    expect(useWorkspaceUi.getState().bots.one.draft).toBe("first");
    resetSessions();
    expect(useWorkspaceUi.getState().bots).toEqual({});
    resetWorkspaceUi();
  });
  it("does not queue decisions or new prompts across connection loss", async () => {
    useSessionStore.getState().connect("bot");
    await waitFor(() => expect(FakeWebSocket.instances.length).toBeGreaterThan(0));
    const socket = FakeWebSocket.instances.at(-1)!;
    socket.observation({ event: "session", session_id: "bot" });
    socket.observation({
      event: "approval_required",
      approval_id: "ap",
      action: "bash",
      detail: "pwd",
    });
    socket.close();
    useSessionStore.getState().decide("bot", "ap", "approve");
    useSessionStore.getState().sendPrompt("bot", "unexpected replay");
    expect(socket.sent).toHaveLength(0);
    expect(sessionFor("bot").status).toBe("awaiting");
    expect(sessionFor("bot").connection).toBe("reconnecting");
    resetSessions();
  });
});
