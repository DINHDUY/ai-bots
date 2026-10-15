import { test, expect } from "@playwright/test";
import { fixture } from "./fixtures";
import type { DeleteCommand, DeletionResult } from "../src/api/deletions.generated";

for (const width of [1600, 390]) {
  test(`workspace deletion recovers a lost response at ${width}px`, async ({ page }) => {
    const { errors } = await fixture(page);
    await page.setViewportSize({ width, height: 1000 });
    const commands: DeleteCommand[] = [];
    let receipt: DeletionResult | null = null;
    await page.route("**/api/workspaces", route => route.fulfill({ json: [
      { id: "personal_duy", name: "Personal workspace", role: "owner" },
      ...(!receipt ? [{ id: "team", name: "Research team", role: "owner" }] : []),
    ] }));
    await page.route("**/api/preferences", route => route.fulfill({ json: { revision: 1, workspace_id: receipt ? "personal_duy" : "team", onboarding: "completed" } }));
    await page.route("**/api/workspace-deletions?*", route => route.fulfill({ json: { items: receipt ? [receipt] : [], next_cursor: null } }));
    await page.route("**/api/workspaces/team/deletion-preview", route => route.fulfill({ json: {
      workspace_id: "team", workspace_name: "Research team", bots: [{ id: "writer", name: "Writer" }], counts: { bots: 1, messages: 4 }, blockers: [], retained: [], preview_digest: "a".repeat(64),
    } }));
    await page.route("**/api/workspaces/team/deletions", async route => {
      const command = route.request().postDataJSON() as DeleteCommand;
      commands.push(command);
      receipt = { request_id: command.request_id, workspace_id: "team", workspace_name: "Research team", deleted_at: "2026-10-12T12:00:00Z", counts: { bots: 1 }, retained: [], cleanup: { state: "complete", remaining: 0, bytes_remaining: 0, errors: [] } };
      await route.abort("failed");
    });
    await page.route("**/api/workspace-deletions/*", route => route.fulfill({ json: receipt }));
    await page.goto("/#/workspace?workspace=team");
    const panel = page.locator(".workspace-deletion");
    await expect(panel).not.toHaveAttribute("open");
    await expect(panel.locator("button.danger")).toBeHidden();
    expect(await panel.evaluate(element => element.nextElementSibling === null)).toBe(true);
    await panel.locator(":scope > summary").click();
    await panel.locator("button.danger").click();
    const dialog = page.getByRole("dialog", { name: "Delete workspace and contents" });
    await expect(dialog.getByRole("button", { name: "Delete workspace and contents", exact: true })).toBeDisabled();
    await dialog.getByLabel("Type the workspace name to confirm").fill("Research team");
    expect(await dialog.evaluate(element => element.scrollWidth <= element.clientWidth)).toBe(true);
    await dialog.getByRole("button", { name: "Delete workspace and contents", exact: true }).click();
    await expect(dialog.getByText(/Deletion result is unknown/)).toBeVisible();
    expect(commands).toHaveLength(1);
    await page.reload();
    await expect(panel).not.toHaveAttribute("open");
    await panel.locator(":scope > summary").click();
    await page.getByRole("button", { name: "Check deletion status" }).click();
    await expect(page.getByText("Workspace deleted.", { exact: true })).toBeVisible();
    await expect(page.getByRole("combobox", { name: "Workspace", exact: true })).toHaveValue("personal_duy");
    await expect(page.getByText(/Cleanup complete/)).toBeVisible();
    expect(commands).toHaveLength(1);
    expect(errors).toEqual([]);
  });
}

test("other tabs leave deleted workspaces and failed file cleanup can be retried", async ({ page, context }) => {
  const other = await context.newPage();
  let removed = false;
  let complete = false;
  let commands = 0;
  const receipt = (): DeletionResult => ({ request_id: "delete-tabs", workspace_id: "team", workspace_name: "Research team", deleted_at: "2026-10-12T12:00:00Z", counts: { bots: 1 }, retained: [], cleanup: { state: complete ? "complete" : "needs_attention", remaining: complete ? 0 : 1, bytes_remaining: complete ? 0 : 7, errors: complete ? [] : ["PermissionError"] } });
  for (const tab of [page, other]) {
    await fixture(tab);
    await tab.route("**/api/workspaces", route => route.fulfill({ json: [{ id: "personal_duy", name: "Personal workspace", role: "owner" }, ...(!removed ? [{ id: "team", name: "Research team", role: "owner" }] : [])] }));
    await tab.route("**/api/workspace-deletions?*", route => route.fulfill({ json: { items: removed ? [receipt()] : [], next_cursor: null } }));
    await tab.route("**/api/workspaces/team/deletion-preview", route => route.fulfill({ json: { workspace_id: "team", workspace_name: "Research team", bots: [], counts: {}, blockers: [], retained: [], preview_digest: "b".repeat(64) } }));
    await tab.route("**/api/workspaces/team/deletions", route => { removed = true; commands++; return route.fulfill({ status: 202, json: receipt() }); });
    await tab.route("**/api/workspace-deletions/delete-tabs/retry-cleanup", route => { complete = true; return route.fulfill({ json: receipt() }); });
    await tab.goto("/#/workspace?workspace=team");
    await expect(tab.getByRole("combobox", { name: "Workspace", exact: true })).toHaveValue("team");
  }
  await page.locator(".workspace-deletion > summary").click();
  await page.locator(".workspace-deletion button.danger").click();
  const dialog = page.getByRole("dialog");
  await dialog.getByLabel("Type the workspace name to confirm").fill("Research team");
  await dialog.getByRole("button", { name: "Delete workspace and contents", exact: true }).click();
  await expect(page.getByText(/File cleanup needs attention/)).toBeVisible();
  await expect(other.getByRole("combobox", { name: "Workspace", exact: true })).toHaveValue("personal_duy", { timeout: 10000 });
  await other.locator(".workspace-deletion > summary").click();
  await expect(other.getByText("The Personal workspace cannot be deleted.")).toBeVisible();
  await page.getByRole("button", { name: "Retry file cleanup" }).click();
  await expect(page.getByText(/Cleanup complete/)).toBeVisible();
  expect(commands).toBe(1);
  await other.route("**/api/workspaces/personal_duy/channel/snapshot", route => route.fulfill({ json: {
    workspace_id: "personal_duy", enabled: 0, revision: 1, seq: 0, role: "owner", enroll_future: false,
    owned_bots: [], directory: { bots: [], revision: 0, next_offset: null }, messages: [], next_before: null, deliveries: [], threads: [],
  } }));
  await other.routeWebSocket("**/api/workspaces/personal_duy/channel/events/ws*", socket => socket.send(JSON.stringify({ events: [], seq: 0 })));
  await other.goto("/#/channel?workspace=team");
  await expect(other.getByRole("combobox", { name: "Workspace", exact: true })).toHaveValue("personal_duy");
  await other.close();
});
