import { test, expect } from "@playwright/test";
import { fixture } from "./fixtures";

test("workspace computer tab saves shared mode", async ({ page }) => {
  await fixture(page);
  let settings = {
    mode: "per_bot",
    provider: "docker",
    profile_id: null,
    ownership: "attached",
    revision: 0,
    role: "owner",
    limitation:
      "Overlapping runs share the desktop, browser, files, and processes. Individual actions run one at a time.",
    attached_bot_ids: [] as string[],
    busy: false,
    computer: null,
  };
  await page.route("**/api/workspaces", (route) =>
    route.fulfill({ json: [{ id: "space", name: "Team workspace", role: "owner" }] }),
  );
  await page.route("**/api/preferences", (route) =>
    route.fulfill({
      json: { workspace_id: "space", onboarding: "completed", revision: 1 },
    }),
  );
  await page.route("**/api/workspaces/space/computer", async (route) => {
    if (route.request().method() === "PUT") {
      settings = {
        ...settings,
        ...route.request().postDataJSON(),
        revision: settings.revision + 1,
        attached_bot_ids: ["alpha", "beta"],
      };
    }
    await route.fulfill({ json: settings });
  });
  await page.goto("/#/workspace?tab=computer&workspace=space");
  await expect(page.getByRole("heading", { name: "Workspace computer" })).toBeVisible();
  await expect(page.getByText(/share the desktop/)).toBeVisible();
  await page.getByLabel("Computer mode").selectOption("shared");
  await expect(page.getByText("Workspace computer settings saved.")).toBeVisible();
  await expect(page.getByText(/2 attached bots/)).toBeVisible();
  expect(settings.mode).toBe("shared");
});
