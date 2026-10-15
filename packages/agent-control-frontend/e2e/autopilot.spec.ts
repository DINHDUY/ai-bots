import { test, expect, type Page, type WebSocketRoute } from "@playwright/test";

async function fixture(page: Page, canManage = true) {
  const stamp = "2026-10-07T12:00:00Z";
  const bot = { id: "auto", name: "Autopilot bot", framework: "microsoft", model: "gpt-4.1", credential_id: "key", instructions: "", created_at: stamp, updated_at: stamp };
  let mode = { bot_id: bot.id, enabled: false, revision: 0, changed_by: null as string | null, changed_at: null as string | null, can_manage: canManage };
  const sockets = new Set<WebSocketRoute>();
  const events: any[] = [];
  const posts: any[] = [];
  let pending = [{ id: "approval", action_id: "action", action: "bash", detail: "python report.py", revision: 1, created_at: stamp }];
  let run = { id: "run", status: "awaiting_approval" };
  const computer = { id: "computer", generation: 1, status: "running" };
  const snapshot = () => ({ schema_version: 2, bot_id: bot.id, snapshot_seq: events.length, autopilot: mode, computer, run, messages: [], messages_before: null, events, pending_approvals: pending, observations_truncated: false });
  function emit(type: string, data: Record<string, unknown>) {
    const event = { schema_version: 2, event_id: `event_${events.length + 1}`, seq: events.length + 1, bot_id: bot.id, run_id: run.id, session_id: computer.id, action_id: "action", occurred_at: stamp, type, data };
    events.push(event);
    for (const socket of sockets) socket.send(JSON.stringify(event));
  }
  emit("approval.required", { approval_id: "approval", action: "bash", detail: "python report.py", revision: 1 });
  const install = async (target: Page) => {
    await target.route("**/api/**", async route => {
      const path = new URL(route.request().url()).pathname;
      if (route.request().method() === "POST" && path.endsWith("/autopilot")) {
        const body = route.request().postDataJSON();
        posts.push(body);
        if (body.expected_revision !== mode.revision) return route.fulfill({ status: 409, json: { detail: "Autopilot changed in another tab" } });
        mode = { ...mode, enabled: body.enabled, revision: mode.revision + 1, changed_by: "owner", changed_at: stamp };
        emit("bot.autopilot.changed", mode);
        if (mode.enabled && pending.length) {
          pending = [];
          run = { ...run, status: "running" };
          emit("approval.resolved", { approval_id: "approval", status: "approved", action: "bash", detail: "python report.py", revision: 2, decision_source: "autopilot", autopilot_revision: mode.revision, decided_by: "owner" });
        }
        return route.fulfill({ json: mode });
      }
      let data: unknown;
      if (path === "/api/me") data = { id: "owner", username: "Ada" };
      else if (path === "/api/capabilities") data = { protocol_version: 2, autopilot: true };
      else if (path === "/api/bots") data = [bot];
      else if (path === "/api/bots/auto") data = { ...bot, messages: [] };
      else if (path.endsWith("/snapshot")) data = snapshot();
      else if (path.endsWith("/autopilot")) data = mode;
      else if (path.endsWith("/computer")) data = { computer, capabilities: { remote_control: true, lifecycle: true } };
      else if (path.endsWith("/control")) data = { paused: false, lease: null };
      else if (path === "/api/credentials" || path.endsWith("/approval-policies")) data = [];
      else if (path === "/api/preferences") data = { revision: 1, order: [], folders: {}, read_cursors: {} };
      else if (path === "/api/workspaces") data = [{ id: "personal", name: "Personal", role: "owner" }];
      else return route.fulfill({ status: 404, json: { detail: "Missing fixture" } });
      return route.fulfill({ json: data });
    });
    await target.routeWebSocket("**/events/ws**", socket => {
      sockets.add(socket);
      socket.onClose(() => { sockets.delete(socket); });
      socket.send(JSON.stringify({ type: "snapshot", data: snapshot() }));
      socket.send(JSON.stringify({ type: "ready", seq: events.length }));
    });
  };
  await install(page);
  return { install, emit, posts };
}

test("enabling resolves pending requests, preserves results on refresh, and synchronizes tabs", async ({ page, context }) => {
  const state = await fixture(page);
  await page.goto("/#/bots/auto");
  await expect(page.getByRole("button", { name: "Allow once" })).toBeVisible();
  await expect(page.getByRole("region", { name: "Autopilot bot conversation" }).getByRole("checkbox", { name: "Autopilot", exact: true })).toHaveCount(0);
  const check = page.locator("header [data-autopilot-toggle]").getByRole("checkbox", { name: "Autopilot", exact: true });
  await check.click();
  await expect(check).toBeChecked();
  await expect(page.getByRole("button", { name: "Allow once" })).toHaveCount(0);
  await expect(page.getByText("Auto-approved by Autopilot", { exact: true }).first()).toBeVisible();
  await expect(page.getByText("Action completed", { exact: true })).toHaveCount(0);
  state.emit("action.started", { operation: "bash", approval_id: "approval" });
  state.emit("action.failed", { operation: "bash", approval_id: "approval", exit_code: 7, ok: false });
  await expect(page.getByText("Exit 7", { exact: true }).first()).toBeVisible();
  await page.reload();
  await expect(check).toBeChecked();
  await expect(page.getByText("Exit 7", { exact: true }).first()).toBeVisible();
  const other = await context.newPage();
  await state.install(other);
  await other.goto("/#/bots/auto");
  const otherCheck = other.locator("header [data-autopilot-toggle]").getByRole("checkbox", { name: "Autopilot", exact: true });
  await expect(otherCheck).toBeChecked();
  await otherCheck.click();
  await expect(check).not.toBeChecked();
  expect(state.posts.map(p => p.expected_revision)).toEqual([0, 1]);
  await page.getByRole("button", { name: "Bot settings", exact: true }).click();
  const settings = page.getByRole("dialog");
  await settings.getByRole("checkbox", { name: "Autopilot", exact: true }).click();
  await expect(otherCheck).toBeChecked();
  await other.close();
});

for (const width of [390, 1024]) {
  test(`Autopilot wraps within the computer panel at ${width}px`, async ({ page }) => {
    await fixture(page);
    await page.setViewportSize({ width, height: 900 });
    await page.goto(width < 500 ? "/#/bots/auto?view=computer" : "/#/bots/auto");
    const toggle = page.locator("header [data-autopilot-toggle]");
    await expect(toggle).toBeVisible();
    const geometry = await toggle.evaluate(element => {
      const rect = element.getBoundingClientRect();
      const header = element.closest("header")!.getBoundingClientRect();
      return { x: rect.x, right: rect.right, bottom: rect.bottom, headerBottom: header.bottom, width: rect.width, scroll: element.scrollWidth, client: element.clientWidth };
    });
    expect(geometry.x).toBeGreaterThanOrEqual(0);
    expect(geometry.right).toBeLessThanOrEqual(width);
    expect(geometry.scroll).toBeLessThanOrEqual(geometry.client + 1);
    expect(geometry.bottom).toBeLessThanOrEqual(geometry.headerBottom);
  });
}

test("Autopilot stays in the mobile computer panel and settings, outside chat", async ({ page }) => {
  const state = await fixture(page);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/#/bots/auto");
  const chat = page.getByRole("region", { name: "Autopilot bot conversation" });
  await expect(chat).toBeVisible();
  await expect(chat.getByRole("checkbox", { name: "Autopilot", exact: true })).toHaveCount(0);
  await page.getByRole("navigation", { name: "Mobile navigation" }).getByRole("link", { name: "Computer", exact: true }).click();
  const check = page.locator("header [data-autopilot-toggle]").getByRole("checkbox", { name: "Autopilot", exact: true });
  await expect(check).toBeVisible();
  await expect(check).toBeEnabled();
  await check.click();
  await expect(check).toBeChecked();
  expect(state.posts).toHaveLength(1);
  await page.getByRole("button", { name: "Bot settings", exact: true }).click();
  await expect(page.getByRole("dialog").getByRole("checkbox", { name: "Autopilot", exact: true })).toBeChecked();
});

test("an older backend explains unavailable Autopilot in settings", async ({ page }) => {
  const state = await fixture(page);
  await page.route("**/api/capabilities", route => route.fulfill({ json: { protocol_version: 2 } }));
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/#/bots/auto");
  const chat = page.getByRole("region", { name: "Autopilot bot conversation" });
  await expect(chat.getByRole("checkbox", { name: "Autopilot", exact: true })).toHaveCount(0);
  await page.getByRole("button", { name: "Bot settings", exact: true }).click();
  await expect(page.getByRole("dialog").getByRole("checkbox", { name: "Autopilot", exact: true })).toBeVisible();
  await expect(page.getByRole("dialog").getByRole("checkbox", { name: "Autopilot", exact: true })).toBeDisabled();
  await expect(page.getByRole("dialog")).toContainText("Backend update required.");
  expect(state.posts).toHaveLength(0);
});
