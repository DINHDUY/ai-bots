import { test, expect } from "@playwright/test";

for (const detail of ["Mac companion is offline", "Accessibility permission required"]) {
  test(`Mac connection rejection stays retryable: ${detail}`, async ({ page }) => {
    const stamp = new Date().toISOString();
    const bot = {
      id: "mac", name: "Mac assistant", framework: "open_interface", model: "gpt-4.1",
      credential_id: "key", instructions: "", created_at: stamp, updated_at: stamp,
    };
    let computer: { id: string; generation: number; status: string } | null = null;
    const requests: string[] = [];
    let ready = false;
    const snapshot = () => ({
      schema_version: 2, bot_id: bot.id, snapshot_seq: 0, computer,
      run: null, health: null, messages: [], messages_before: null, events: [],
      pending_approvals: [], observations_truncated: false,
    });
    await page.route("**/api/**", async (route) => {
      const path = new URL(route.request().url()).pathname;
      let data: unknown;
      if (path === "/api/me") data = { id: "owner", username: "Ada" };
      else if (path === "/api/bots") data = [bot];
      else if (path === "/api/bots/mac") data = { ...bot, messages: [] };
      else if (path === "/api/capabilities") data = { protocol_version: 2, frameworks: ["open_interface"], macos_computers: true };
      else if (path === "/api/preferences") data = { revision: 0, folders: {}, order: [] };
      else if (path === "/api/workspaces") data = [{ id: "personal", name: "Personal", role: "owner" }];
      else if (path.endsWith("/snapshot")) data = snapshot();
      else if (path.endsWith("/lifecycle/create")) {
        const body = route.request().postDataJSON();
        expect(body.generation).toBe(computer?.generation ?? 0);
        requests.push(body.request_id);
        computer = { id: `mac-session-${requests.length}`, generation: requests.length, status: ready ? "running" : "closed" };
        data = { status: ready ? "completed" : "failed", detail: ready ? undefined : detail, computer };
      } else if (path.endsWith("/computer")) data = {
        computer, provider: "macos_local", local_control: false,
        reason: ready ? "Enable Allow agent control in the macOS companion" : detail,
        capabilities: { lifecycle: true, remote_control: false, desktop_takeover: true },
      };
      else if (path.endsWith("/control")) data = { paused: true, lease: null };
      else return route.fulfill({ status: 404, json: { detail: "Unavailable fixture" } });
      return route.fulfill({ json: data });
    });
    await page.routeWebSocket("**/events/ws**", (socket) => {
      socket.send(JSON.stringify({ type: "snapshot", data: snapshot() }));
      socket.send(JSON.stringify({ type: "ready", seq: 0 }));
    });
    await page.goto("/#/bots/mac?view=computer");
    await page.getByRole("button", { name: "Connect Mac", exact: true }).click();
    await expect(page.getByRole("alert")).toContainText(detail);
    await expect(page.getByRole("button", { name: "Connect Mac", exact: true })).toBeEnabled();
    await expect(page.getByLabel("Mac recovery required")).toHaveCount(0);
    expect(requests).toHaveLength(1);
    ready = true;
    await page.getByRole("button", { name: "Connect Mac", exact: true }).click();
    await expect(page.getByRole("button", { name: "Take control on this Mac" })).toBeVisible();
    await expect(page.getByRole("alert")).toHaveCount(0);
    expect(requests).toHaveLength(2);
    expect(requests[0]).not.toBe(requests[1]);
    await page.reload();
    await expect(page.getByLabel("Mac recovery required")).toHaveCount(0);
    expect(requests).toHaveLength(2);
  });
}
