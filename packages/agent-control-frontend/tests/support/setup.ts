import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterAll, afterEach, beforeAll, vi } from "vitest";

import { resetSessions } from "../../src/session/store";
import { FakeWebSocket } from "./fakeSocket";
import { resetState, server } from "./server";

beforeAll(() => {
  HTMLDialogElement.prototype.showModal = function () {
    this.setAttribute("open", "");
  };
  HTMLDialogElement.prototype.close = function () {
    this.removeAttribute("open");
  };
  server.listen({ onUnhandledRequest: "error" });
  vi.stubGlobal("WebSocket", FakeWebSocket);
});

afterEach(() => {
  cleanup();
  resetSessions();
  FakeWebSocket.instances = [];
  resetState();
  server.resetHandlers();
  localStorage.clear();
  vi.stubGlobal("WebSocket", FakeWebSocket);
});

afterAll(() => server.close());
