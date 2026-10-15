import { test, expect, type Page } from "@playwright/test";

async function fixture(page: Page, options: { paused?: boolean; remoteControl?: boolean; writable?: boolean } = {}) {
  const bot = { id: "services", name: "Service bot", framework: "microsoft", model: "gpt-4.1", instructions: "", credential_id: "key", created_at: "2026-10-07T00:00:00Z", updated_at: "2026-10-07T00:00:00Z" };
  const stamp = new Date().toISOString();
  const capture = { surface_id: "browser_epoch_1", surface_kind: "browser", width: 1024, height: 768, captured_at: stamp, sequence: 1, viewport_revision: "browser_1024x768" };
  const health = { compatible: true, health: "healthy", observed_at: stamp, services: { browser: true, desktop: true, files: true } };
  const event = { schema_version: 2, event_id: "capture_event", seq: 1, bot_id: bot.id, session_id: "computer_services", run_id: null, occurred_at: stamp, type: "capture.available", data: { capture_id: "capture_1", url: "/api/bots/services/captures/capture_1", capture } };
  const snapshot = { schema_version: 2, bot_id: bot.id, snapshot_seq: 1, computer: { id: "computer_services", generation: 1, status: "running" }, run: null, messages: [], messages_before: null, events: [event], pending_approvals: [], observations_truncated: false, health };
  const requests: { path: string; body: any }[] = [];
  const inputs: any[] = [];
  let lease: any = null;
  let paused = options.paused ?? false;
  let prefs = { revision: 0, workspace_id: "personal", onboarding: "dismissed", avatar: "", display_role: "", order: [], folders: {}, read_cursors: {} };
  let routines: any[] = [];
  await page.route("**/api/**", async route => {
    const request = route.request(), path = new URL(request.url()).pathname;
    if (request.method() !== "GET") {
      const body = request.postDataJSON(); requests.push({ path, body });
      if (path.endsWith("/control/acquire")) { paused = true; lease = { id: "lease_services", session_id: "computer_services", generation: 1, client_id: body.client_id, fence: 1, surface: "browser", surface_id: capture.surface_id, viewport_revision: capture.viewport_revision, last_sequence: 0 }; return route.fulfill({ json: lease }); }
      if (path.endsWith("/control/release")) { lease = null; return route.fulfill({ json: { paused: true } }); }
      if (path.endsWith("/control/resume")) { paused = false; return route.fulfill({ json: { run_id: "resumed", status: "preparing" } }); }
      if (path === "/api/preferences") { prefs = { ...body, revision: prefs.revision + 1 }; return route.fulfill({ json: prefs }); }
      if (path.endsWith("/routines") && request.method() === "POST") { routines = [{ id: "routine_1", version: 1, enabled: 1, next_at: null, definition: body }]; return route.fulfill({ json: routines[0] }); }
      if (path.endsWith("/run")) return route.fulfill({ json: { id: "job_1", state: "claimed" } });
      return route.fulfill({ json: { status: "completed" } });
    }
    let data: unknown;
    if (path === "/api/me") data = { id: "owner", username: "Ada" };
    else if (path === "/api/bots") data = [bot];
    else if (path === "/api/bots/services") data = { ...bot, messages: [] };
    else if (path === "/api/capabilities") data = { protocol_version: 2 };
    else if (path === "/api/preferences") data = prefs;
    else if (path === "/api/workspaces") data = [{ id: "personal", name: "Personal", role: "owner" }];
    else if (path.endsWith("/members")) data = [{ user_id: "owner", username: "Ada", role: "owner" }];
    else if (path.endsWith("/groups")) data = [];
    else if (path.endsWith("/routines")) data = routines;
    else if (path.endsWith("/history")) data = [{ id: "job_1", state: "awaiting_approval", bot_id: bot.id, created_at: stamp }];
    else if (path.endsWith("/snapshot")) data = snapshot;
    else if (path.endsWith("/computer")) data = { ...health, computer: snapshot.computer, capabilities: { lifecycle: options.writable ?? true, remote_control: options.remoteControl ?? true } };
    else if (path.endsWith("/control")) data = { paused, lease };
    else if (path.endsWith("/captures/latest")) data = event.data;
    else if (path.endsWith("/captures/capture_1")) return route.fulfill({ contentType: "image/png", body: Buffer.from("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII=", "base64") });
    else if (path.endsWith("/files")) data = { entries: [{ path: "/workspace/report.csv", name: "report.csv", kind: "file", size: 100000, protected: false }], cursor: null };
    else if (path.endsWith("/file-preview")) data = { path: "/workspace/report.csv", text: "date,total\n2026-10-07,42", returned_bytes: 65536, size: 100000, truncated: true, revision: "content_sha", protected: false };
    else if (path === "/api/credentials") data = [];
    else return route.fulfill({ status: 404, json: { detail: "Missing fixture route" } });
    return route.fulfill({ json: data });
  });
  await page.routeWebSocket("**/events/ws**", socket => { socket.send(JSON.stringify({ type: "snapshot", data: snapshot })); socket.send(JSON.stringify({ type: "ready", seq: 1 })); });
  await page.routeWebSocket("**/control/ws**", socket => { socket.onMessage(raw => { const message = JSON.parse(String(raw)); inputs.push(message); socket.send(JSON.stringify({ status: "applied", sequence: message.sequence })); }); });
  return { requests, inputs };
}

test("human input carries surface and lease fences and release stays paused", async ({ page }) => {
  const state = await fixture(page);
  await page.goto("/#/bots/services?view=computer&tab=screen");
  await expect(page.getByRole("button", { name: "Take control", exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Take control", exact: true }).click();
  await expect(page.getByText("Human input enabled", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Resume agent", exact: true })).toBeDisabled();
  const image = page.getByRole("img", { name: /^Sandbox capture/ }).first();
  await image.click();
  await expect.poll(() => state.inputs.length).toBeGreaterThanOrEqual(2);
  expect(state.inputs[0]).toMatchObject({ lease_id: "lease_services", fence: 1, generation: 1, surface_id: "browser_epoch_1", capture_id: "capture_1", sequence: 1 });
  expect(state.inputs[0].input.x).toBeGreaterThanOrEqual(0);
  expect(state.inputs[0].input.x).toBeLessThan(1024);
  await page.getByRole("button", { name: "Release control", exact: true }).click();
  await expect(page.getByRole("button", { name: "Resume agent", exact: true })).toBeVisible();
  expect(state.requests.some(r => r.path.endsWith("/control/resume"))).toBe(false);
  await page.getByRole("button", { name: "Resume agent", exact: true }).click();
  expect(state.requests.some(r => r.path.endsWith("/control/resume"))).toBe(true);
  await expect(page.getByRole("button", { name: "Resume agent", exact: true })).toHaveCount(0);
});

test("paused agent can resume from the computer panel without remote input support", async ({ page }) => {
  const state = await fixture(page, { paused: true, remoteControl: false });
  await page.goto("/#/bots/services?view=computer");
  await expect(page.getByRole("button", { name: "Take control", exact: true })).toHaveCount(0);
  const resume = page.getByRole("button", { name: "Resume agent", exact: true });
  await expect(resume).toBeEnabled();
  await resume.click();
  await expect(resume).toHaveCount(0);
  expect(state.requests.filter(r => r.path.endsWith("/control/resume"))).toHaveLength(1);
});

test("mobile chat exposes the paused agent action above the message box after refresh", async ({ page }) => {
  const state = await fixture(page, { paused: true });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/#/bots/services");
  await page.reload();
  const notice = page.locator('[aria-label="Agent paused"]');
  await expect(notice).toBeVisible();
  const button = notice.getByRole("button", { name: "Resume agent", exact: true });
  await expect(button).toBeEnabled();
  const noticeBox = await notice.boundingBox();
  const messageBox = await page.getByRole("textbox", { name: "Message", exact: true }).boundingBox();
  expect(noticeBox!.y + noticeBox!.height).toBeLessThan(messageBox!.y);
  expect(noticeBox!.x + noticeBox!.width).toBeLessThanOrEqual(390);
  await button.click();
  await expect(notice).toHaveCount(0);
  expect(state.requests.filter(r => r.path.endsWith("/control/resume"))).toHaveLength(1);
});

test("resume errors stay visible and viewers cannot resume a paused agent", async ({ page }) => {
  const state = await fixture(page, { paused: true });
  await page.route("**/control/resume", route => route.fulfill({ status: 409, json: { detail: "Release human control and terminals before resuming." } }));
  await page.goto("/#/bots/services");
  const notice = page.locator('[aria-label="Agent paused"]');
  await notice.getByRole("button", { name: "Resume agent", exact: true }).click();
  await expect(notice.getByRole("alert")).toHaveText("Release human control and terminals before resuming.");
  await expect(notice).toBeVisible();
  await page.route("**/api/bots/services/computer", route => route.fulfill({ json: {
    computer: { id: "computer_services", generation: 1, status: "running" },
    capabilities: { lifecycle: false, remote_control: false },
  } }));
  await page.reload();
  await expect(notice.getByRole("button", { name: "Resume agent", exact: true })).toBeDisabled();
  await expect(notice).toContainText("an operator with execution access");
  expect(state.requests.some(r => r.path.endsWith("/control/resume"))).toBe(false);
});

test("file preview stays partial while download binds the complete revision", async ({ page }) => {
  await fixture(page);
  await page.goto("/#/bots/services?view=computer&tab=files");
  await page.getByRole("button", { name: "report.csv", exact: true }).click();
  await expect(page.getByText(/Partial preview/)).toBeVisible();
  await expect(page.getByRole("link", { name: "Download complete file" })).toHaveAttribute("href", /file-content\?path=.*report.csv&revision=content_sha/);
});

test("routine editor submits a real definition and exposes admitted job history", async ({ page }) => {
  const state = await fixture(page);
  await page.goto("/#/workspace");
  await page.getByRole("button", { name: "Routines", exact: true }).click();
  await page.getByLabel("Name", { exact: true }).fill("Daily report");
  await page.getByLabel("Task", { exact: true }).fill("Summarize the workspace files");
  await page.getByRole("button", { name: "Save routine", exact: true }).click();
  await expect(page.getByText("Daily report", { exact: true })).toBeVisible();
  expect(state.requests.find(r => r.path === "/api/workspaces/personal/routines")?.body).toMatchObject({ name: "Daily report", bot_id: "services", trigger: "manual", enabled: true });
  await page.getByRole("button", { name: "Run now", exact: true }).click();
  await expect(page.getByText("awaiting_approval", { exact: true })).toBeVisible();
  await expect(page.getByRole("link", { name: "Open run and approvals" })).toHaveAttribute("href", "#/bots/services");
});
