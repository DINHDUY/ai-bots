import { test, expect, type WebSocketRoute } from "@playwright/test";

test("Windows workspace shows local controls and pairing at desktop and mobile widths", async ({
  page,
}) => {
  const stamp = new Date().toISOString();
  const bot = {
    id: "windows",
    name: "Desktop assistant",
    framework: "ufo",
    model: "gpt-4.1",
    credential_id: "key",
    instructions: "",
    created_at: stamp,
    updated_at: stamp,
  };
  const computer = { id: "windows-session", generation: 1, status: "running" };
  let requestedSurface: string | null = null;
  const snapshot = {
    schema_version: 2,
    bot_id: bot.id,
    snapshot_seq: 0,
    computer,
    health: {
      health: "healthy", compatible: true, observed_at: stamp,
      services: { desktop: true },
    },
    run: null,
    messages: [], messages_before: null,
    events: [],
    pending_approvals: [],
    observations_truncated: false,
  };
  await page.route("**/api/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    let data: unknown;
    if (path === "/api/me") data = { id: "owner", username: "Ada" };
    else if (path === "/api/bots") data = [bot];
    else if (path === "/api/bots/windows") data = { ...bot, messages: [] };
    else if (path === "/api/capabilities")
      data = {
        protocol_version: 2,
        frameworks: ["anthropic", "microsoft", "ufo"],
        windows_computers: true,
      };
    else if (path === "/api/preferences")
      data = { revision: 0, folders: {}, order: [] };
    else if (path === "/api/workspaces")
      data = [{ id: "personal", name: "Personal", role: "owner" }];
    else if (path.endsWith("/snapshot")) data = snapshot;
    else if (path.endsWith("/computer/capture")) {
      requestedSurface = new URL(route.request().url()).searchParams.get("surface");
      if (requestedSurface !== "desktop") {
        return route.fulfill({ status: 409, json: { detail: "This Windows provider exposes the Desktop surface" } });
      }
      data = { capture_id: "first-windows-capture" };
    }
    else if (path.endsWith("/computer"))
      data = {
        computer,
        provider: "windows_local",
        local_control: false,
        reason: "Control off locally",
        capabilities: {
          lifecycle: true,
          remote_control: false,
          desktop_takeover: true,
        },
      };
    else if (path.endsWith("/control")) data = { paused: true, lease: null };
    else if (path.endsWith("/compute-config"))
      data = { device_id: "pc-test", revision: 1 };
    else if (path === "/api/computers")
      data = {
        computers: [
          {
            id: "pc-test",
            name: "My Windows PC",
            online: true,
            state: { ready: true, sharing: true, armed: false },
          },
        ],
      };
    else if (path === "/api/credentials")
      data = [{ id: "key", provider: "openai", label: "Model key" }];
    else if (path.endsWith("/approval-policies")) data = [];
    else
      return route.fulfill({
        status: 404,
        json: { detail: "Unavailable fixture" },
      });
    return route.fulfill({ json: data });
  });
  await page.routeWebSocket("**/events/ws**", (socket) => {
    socket.send(JSON.stringify({ type: "snapshot", data: snapshot }));
    socket.send(JSON.stringify({ type: "ready", seq: 0 }));
  });
  await page.goto("/#/bots/windows?view=computer");
  await expect(
    page.getByRole("heading", { name: "Local Windows PC" }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Take control on this PC" }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Resume agent", exact: true }),
  ).toBeDisabled();
  await expect(
    page.getByRole("button", { name: "Hibernate", exact: true }),
  ).toHaveCount(0);
  await expect(page.getByRole("tab", { name: "Terminal" })).toHaveCount(0);
  await expect(page.getByRole("tab", { name: "Filesystem" })).toHaveCount(0);
  await expect(page.getByText(/select your paired PC and click Use this PC/)).toBeVisible();
  await page.getByRole("button", { name: "Capture now" }).click();
  await expect.poll(() => requestedSurface).toBe("desktop");
  await page.getByRole("button", { name: "Disconnect Windows PC" }).click();
  await expect(page.getByRole("dialog")).toContainText(
    "Your Windows applications and files remain",
  );
  await page.getByRole("button", { name: "Keep open" }).click();
  await page.getByRole("button", { name: "Bot settings", exact: true }).click();
  await expect(page.getByLabel("Paired Windows computer")).toHaveValue(
    "pc-test",
  );
  await expect(page.getByText(/My Windows PC is assigned to this bot/)).toBeVisible();
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(
    page.getByRole("button", { name: "Pair a Windows PC", exact: true }),
  ).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
});

test("a ready companion keeps recovery visible until explicit disconnect and reconnect", async ({ page }) => {
  const stamp = new Date().toISOString();
  const bot = {
    id: "windows", name: "Desktop assistant", framework: "ufo", model: "gpt-4.1",
    credential_id: "key", instructions: "", created_at: stamp, updated_at: stamp,
  };
  let computer = { id: "failed-session", generation: 1, status: "failed" };
  let seq = 1;
  let closeCalls = 0;
  let connectCalls = 0;
  let socket: WebSocketRoute | undefined;
  const snapshot = () => ({
    schema_version: 2, bot_id: bot.id, snapshot_seq: seq, computer,
    run: { id: "old-run", session_id: "failed-session", status: "interrupted" },
    health: { health: "healthy", compatible: true, observed_at: stamp, services: { desktop: true } },
    messages: [], messages_before: null, events: [], pending_approvals: [], observations_truncated: false,
  });
  function publish(type: string) {
    seq += 1;
    socket?.send(JSON.stringify({
      schema_version: 2, event_id: `recovery-${seq}`, bot_id: bot.id, seq,
      session_id: computer.id, run_id: null, occurred_at: stamp, type,
      data: { status: computer.status },
    }));
  }
  await page.route("**/api/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    let data: unknown;
    if (path === "/api/me") data = { id: "owner", username: "Ada" };
    else if (path === "/api/bots") data = [bot];
    else if (path === "/api/bots/windows") data = { ...bot, messages: [] };
    else if (path === "/api/capabilities") data = { protocol_version: 2, frameworks: ["ufo"], windows_computers: true };
    else if (path === "/api/preferences") data = { revision: 0, folders: {}, order: [] };
    else if (path === "/api/workspaces") data = [{ id: "personal", name: "Personal", role: "owner" }];
    else if (path.endsWith("/snapshot")) data = snapshot();
    else if (path.endsWith("/computer/close")) {
      closeCalls += 1;
      expect(route.request().postDataJSON().session_id).toBe("failed-session");
      if (closeCalls === 1) return route.fulfill({ status: 409, json: { detail: "Disconnect could not be confirmed. Try again." } });
      computer = { ...computer, status: "closed" };
      publish("session.closed");
      data = { status: "closed", session_id: computer.id };
    } else if (path.endsWith("/lifecycle/create")) {
      connectCalls += 1;
      expect(route.request().postDataJSON().generation).toBe(1);
      computer = { id: "new-session", generation: 2, status: "running" };
      publish("session.bound");
      data = { status: "completed" };
    } else if (path.endsWith("/computer")) data = {
      computer, provider: "windows_local", local_control: true, reason: "Ready",
      capabilities: { lifecycle: true, remote_control: false, desktop_takeover: true },
    };
    else if (path.endsWith("/control")) data = { paused: false, lease: null };
    else return route.fulfill({ status: 404, json: { detail: "Unavailable fixture" } });
    return route.fulfill({ json: data });
  });
  await page.routeWebSocket("**/events/ws**", (route) => {
    socket = route;
    route.send(JSON.stringify({ type: "snapshot", data: snapshot() }));
    route.send(JSON.stringify({ type: "ready", seq }));
  });
  await page.goto("/#/bots/windows");
  await expect(page.locator(".badge").filter({ hasText: "Recovery required" })).toBeVisible();
  await expect(page.getByText(/A ready companion does not clear/)).toBeVisible();
  await expect(page.getByRole("button", { name: "Resume agent", exact: true })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Connect Windows PC", exact: true })).toHaveCount(0);
  expect(closeCalls).toBe(0);
  expect(connectCalls).toBe(0);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.getByRole("button", { name: "Review and disconnect" }).click();
  await expect(page.getByRole("dialog")).toContainText("Your Windows applications and files remain");
  await page.getByRole("button", { name: "Disconnect PC", exact: true }).click();
  await expect(page.getByRole("dialog").getByRole("alert")).toHaveText("Disconnect could not be confirmed. Try again.");
  await expect(page.getByRole("button", { name: "Disconnect PC", exact: true })).toBeEnabled();
  await page.getByRole("button", { name: "Disconnect PC", exact: true }).click();
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Review and disconnect" })).toHaveCount(0);
  await page.getByRole("navigation", { name: "Mobile navigation" }).getByRole("link", { name: "Computer", exact: true }).click();
  await page.getByRole("button", { name: "Connect Windows PC", exact: true }).click();
  await expect(page.getByRole("button", { name: "Take control on this PC" })).toBeVisible();
  await expect(page.getByText("Windows PC disconnected. Captures below are historical.")).toHaveCount(0);
  expect(closeCalls).toBe(2);
  expect(connectCalls).toBe(1);
  await page.reload();
  await expect(page.getByRole("heading", { name: "Local Windows PC" })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.setViewportSize({ width: 1600, height: 1000 });
  await expect(page.getByRole("region", { name: "Local Windows PC", exact: true }).locator("header").first().locator(".badge").filter({ hasText: "Idle" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Review and disconnect" })).toHaveCount(0);
});
