import { expect, it } from "vitest";
import { parseWireFrame } from "../../src/api/wire";

const event = { schema_version: 2, event_id: "event", seq: 1, bot_id: "bot", session_id: null,
  run_id: null, occurred_at: "2026-10-09T00:00:00Z", type: "run.finished", data: { status: "completed" } };

it("accepts additive domain events inside the supported envelope", () => {
  expect(parseWireFrame(JSON.stringify(event))).toEqual(event);
  expect(parseWireFrame(JSON.stringify({ ...event, type: "future.capability" }))).toHaveProperty("seq", 1);
});

it.each([{ schema_version: 3 }, { seq: -1 }, { seq: "1" }, { bot_id: null }, { data: [] }])(
  "rejects unsupported or malformed replay %j", change => {
    expect(() => parseWireFrame(JSON.stringify({ ...event, ...change }))).toThrow();
  },
);

it("rejects an incomplete snapshot before the reducer receives it", () => {
  expect(() => parseWireFrame(JSON.stringify({ type: "snapshot", data: { schema_version: 2 } }))).toThrow();
});
