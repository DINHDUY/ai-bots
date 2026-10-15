import { describe, expect, it } from "vitest";

import { appendUser, emptySession, parseToolCall, reduceFrame } from "../../src/session/reduce";

describe("parseToolCall", () => {
  it("splits terminal commands from output", () => {
    expect(parseToolCall("run_terminal_command: ls -la\ntotal 1")).toEqual({
      command: "ls -la",
      output: "total 1",
    });
    expect(parseToolCall("bash: pwd\n/workspace")).toEqual({
      command: "pwd",
      output: "/workspace",
    });
    expect(parseToolCall("mutate_file: notes.txt")).toBeNull();
  });
});

describe("reduceFrame", () => {
  it("maps log, screenshot, artifact, and status frames", () => {
    let state = emptySession();
    state = reduceFrame(state, { event: "session", session_id: "b1" }).state;
    expect(state.status).toBe("running");

    state = reduceFrame(state, {
      event: "log",
      type: "THOUGHT",
      payload: "looking",
    }).state;
    state = reduceFrame(state, {
      event: "log",
      type: "SYSTEM",
      payload: "ready",
    }).state;
    state = reduceFrame(state, {
      event: "log",
      type: "TOOL_CALL",
      payload: "bash: ls\nfile.txt",
    }).state;
    state = reduceFrame(state, {
      event: "log",
      type: "TOOL_CALL",
      payload: "browser_click: button",
    }).state;
    state = reduceFrame(state, {
      event: "log",
      type: "SCREENSHOT_CAPTURE",
      payload: "abc",
    }).state;
    state = reduceFrame(state, {
      event: "artifact_written",
      meta: { path: "/workspace/out.txt", preview: "done" },
    }).state;
    state = reduceFrame(state, {
      event: "log",
      type: "RESULT",
      payload: "finished",
    }).state;
    state = reduceFrame(state, { event: "done", session_id: "b1" }).state;

    expect(state.status).toBe("idle");
    expect(state.items.map((item) => item.kind)).toEqual([
      "thought",
      "system",
      "assistant",
    ]);
    expect(state.terminal).toHaveLength(1);
    expect(state.terminal[0]).toMatchObject({
      command: "ls",
      output: "file.txt",
    });
    expect(state.activity).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          kind: "tool",
          detail: "browser_click: button",
        }),
      ]),
    );
    expect(state.shots[0]?.src).toBe("data:image/png;base64,abc");
    expect(state.files[0]).toMatchObject({
      path: "/workspace/out.txt",
      preview: "done",
    });
  });

  it("joins consecutive thought tokens into one thinking process", () => {
    let state = emptySession();
    for (const payload of ["Let", " me", " check"])
      state = reduceFrame(state, {
        event: "log",
        type: "THOUGHT",
        payload,
      }).state;
    expect(state.items).toHaveLength(1);
    expect(state.items[0]).toMatchObject({
      kind: "thought",
      text: "Let me check",
    });
    expect(state.thoughtOpen).toBe(true);
    const firstId = state.items[0].id;

    state = reduceFrame(state, {
      event: "log",
      type: "TOOL_CALL",
      payload: "bash: ls\nfile.txt",
    }).state;
    state = reduceFrame(state, {
      event: "log",
      type: "THOUGHT",
      payload: "next",
    }).state;
    expect(state.items.filter((item) => item.kind === "thought")).toEqual([
      expect.objectContaining({ id: firstId, text: "Let me check" }),
      expect.objectContaining({ text: "next" }),
    ]);

    state = reduceFrame(state, {
      event: "log",
      type: "RESULT",
      payload: "finished",
    }).state;
    state = reduceFrame(state, {
      event: "log",
      type: "THOUGHT",
      payload: "again",
    }).state;
    expect(state.items.map((item) => item.kind)).toEqual([
      "thought",
      "thought",
      "assistant",
      "thought",
    ]);
    expect(state.items.at(-1)).toMatchObject({ text: "again" });

    state = appendUser(state, "continue");
    state = reduceFrame(state, {
      event: "log",
      type: "THOUGHT",
      payload: "fresh",
    }).state;
    expect(state.items.at(-1)).toMatchObject({ kind: "thought", text: "fresh" });
  });

  it("pauses for approval and auto-replies when the action is always allowed", () => {
    const waiting = reduceFrame(emptySession(), {
      event: "approval_required",
      approval_id: "ap1",
      action: "bash",
      detail: "rm data",
    });
    expect(waiting.send).toBeNull();
    expect(waiting.state.status).toBe("awaiting");
    expect(waiting.state.items[0]).toMatchObject({ kind: "approval" });
    expect(waiting.state.items[0]).not.toHaveProperty("decision");

    const allowed = reduceFrame(
      { ...emptySession(), alwaysAllow: ["bash"] },
      {
        event: "approval_required",
        approval_id: "ap2",
        action: "bash",
        detail: "ls",
      },
    );
    expect(allowed.state.status).toBe("awaiting");
    expect(allowed.send).toBeNull();
    expect(allowed.state.items[0]).not.toHaveProperty("decision");
  });

  it("records error and closed states", () => {
    const failed = reduceFrame(emptySession(), {
      event: "log",
      type: "ERROR",
      payload: "stopped",
    });
    expect(failed.state.status).toBe("error");
    expect(failed.state.items[0]).toMatchObject({
      kind: "error",
      text: "stopped",
    });

    const closed = reduceFrame(failed.state, {
      event: "closed",
      session_id: "b1",
    });
    expect(closed.state.status).toBe("closed");

    const socketError = reduceFrame(emptySession(), {
      event: "error",
      payload: "cancelled",
    });
    expect(socketError.state.status).toBe("error");
    expect(socketError.state.items[0]).toMatchObject({ text: "cancelled" });
  });
});
