import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { expect, it } from "vitest";
import { server } from "../../support/server";
import { useSessionStore } from "../../../src/session/store";
import { AutopilotToggle } from "../../../src/features/bots/AutopilotToggle";

const initial = { bot_id: "bot", enabled: false, revision: 0, changed_by: null, changed_at: null, can_manage: true };
function mount(copies = 1, showUnavailable = false) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={client}>{Array.from({ length: copies }, (_, i) => <AutopilotToggle key={i} botId="bot" showUnavailable={showUnavailable} />)}</QueryClientProvider>);
  return client;
}
function fixtures(canManage = true) {
  server.use(
    http.get("*/api/capabilities", () => HttpResponse.json({ autopilot: true })),
    http.get("*/api/bots/bot/autopilot", () => HttpResponse.json({ ...initial, can_manage: canManage })),
  );
}

it("waits for acknowledgement, shares saving state, and rejects an older response", async () => {
  fixtures();
  let release!: () => void;
  const pending = new Promise<void>(resolve => { release = resolve; });
  let sent: Record<string, unknown> | undefined;
  server.use(http.post("*/api/bots/bot/autopilot", async ({ request }) => {
    sent = await request.json() as Record<string, unknown>;
    await pending;
    return HttpResponse.json({ ...initial, enabled: true, revision: 1, changed_by: "owner" });
  }));
  mount(2);
  const checks = await screen.findAllByRole("checkbox", { name: "Autopilot" });
  await waitFor(() => expect(checks[0]).toBeEnabled());
  await userEvent.click(checks[0]!);
  await waitFor(() => expect(sent?.expected_revision).toBe(0));
  expect(sent?.request_id).toBeTruthy();
  for (const check of checks) { expect(check).toBeDisabled(); expect(check).not.toBeChecked(); }
  act(() => useSessionStore.getState().setAutopilot("bot", { ...initial, revision: 2, changed_by: "owner" }));
  release();
  await waitFor(() => expect(checks[0]).toBeEnabled());
  for (const check of checks) expect(check).not.toBeChecked();
});

it("keeps the confirmed setting on errors and uses refreshed revisions for retry", async () => {
  fixtures();
  let attempts = 0;
  server.use(http.post("*/api/bots/bot/autopilot", async ({ request }) => {
    attempts++;
    const body = await request.json() as Record<string, unknown>;
    if (attempts === 1) return HttpResponse.json({ detail: "Changed in another tab" }, { status: 409 });
    expect(body.expected_revision).toBe(0);
    return HttpResponse.json({ ...initial, enabled: true, revision: 1, changed_by: "owner" });
  }));
  mount();
  const check = await screen.findByRole("checkbox", { name: "Autopilot" });
  await waitFor(() => expect(check).toBeEnabled());
  await userEvent.click(check);
  await screen.findByRole("alert");
  expect(check).not.toBeChecked();
  await userEvent.click(check);
  await waitFor(() => expect(check).toBeChecked());
});

it("shows members a read-only setting", async () => {
  fixtures(false);
  mount();
  await screen.findByText("Only the bot owner can change Autopilot.");
  expect(screen.getByRole("checkbox", { name: "Autopilot" })).toBeDisabled();
});

it("hides the feature for older backends", async () => {
  server.use(http.get("*/api/capabilities", () => HttpResponse.json({ protocol_version: 2 })));
  const client = mount();
  await waitFor(() => expect(client.getQueryData(["capabilities"])).toBeDefined());
  expect(screen.queryByRole("checkbox", { name: "Autopilot" })).toBeNull();
});

it("explains unavailable Autopilot in settings", async () => {
  server.use(http.get("*/api/capabilities", () => HttpResponse.json({ protocol_version: 2 })));
  mount(1, true);
  await screen.findByText(/Backend update required/);
  expect(screen.getByRole("checkbox", { name: "Autopilot" })).toBeDisabled();
});

it("retries a lost response with the same request ID", async () => {
  fixtures();
  const bodies: unknown[] = [];
  server.use(http.post("*/api/bots/bot/autopilot", async ({ request }) => {
    bodies.push(await request.json());
    if (bodies.length === 1) return HttpResponse.error();
    return HttpResponse.json({ ...initial, enabled: true, revision: 1, changed_by: "owner" });
  }));
  mount();
  const check = await screen.findByRole("checkbox", { name: "Autopilot" });
  await waitFor(() => expect(check).toBeEnabled());
  await userEvent.click(check);
  await waitFor(() => expect(check).toBeChecked(), { timeout: 3000 });
  expect(bodies).toHaveLength(2);
  expect(bodies[0]).toEqual(bodies[1]);
});
