import { test, expect } from "@playwright/test";
import { fixture } from "./fixtures";

for (const width of [1600, 390]) {
  test(`screenshot retention saves and fits at ${width}px`, async ({
    page,
  }) => {
    const f = await fixture(page);
    await page.setViewportSize({ width, height: 900 });
    let settings = {
      revision: 1,
      role: "owner",
      max_count: null as number | null,
      max_bytes: null as number | null,
      reserve_percent: 25,
      cleanup_target_percent: 50,
      max_age_seconds: 604800,
      shared_limit_bytes: 2 * 1024 ** 3,
      cleanup_pending: false,
      last_cleanup_at: null,
      last_error: null,
      usage: {
        retained_count: 42,
        screenshot_bytes: 6000,
        pending_bytes: 0,
        shared_bytes: 9000,
      },
    };
    await page.route("**/api/workspaces", (route) =>
      route.fulfill({
        json: [{ id: "space", name: "Team workspace", role: "owner" }],
      }),
    );
    await page.route("**/api/preferences", (route) =>
      route.fulfill({
        json: { workspace_id: "space", onboarding: "completed", revision: 1 },
      }),
    );
    await page.route(
      "**/api/workspaces/space/capture-retention",
      async (route) => {
        if (route.request().method() === "PATCH")
          settings = {
            ...settings,
            ...route.request().postDataJSON(),
            revision: settings.revision + 1,
          };
        await route.fulfill({ json: settings });
      },
    );
    await page.route(
      "**/api/workspaces/space/capture-retention/preview",
      (route) =>
        route.fulfill({ json: { remove_count: 10, remove_bytes: 2000 } }),
    );
    await page.goto("/#/workspace?tab=storage&workspace=space");
    await expect(
      page.getByRole("heading", { name: "Screenshot retention" }),
    ).toBeVisible();
    await page.getByLabel("Keep latest screenshots").check();
    await page.getByLabel("Maximum screenshots").fill("32");
    await page.getByLabel("Limit screenshot storage").check();
    await page.getByLabel("Retention period").selectOption("86400");
    await expect(page.getByText(/At 75%/)).toContainText("50%");
    const save = page.getByRole("button", { name: "Save", exact: true });
    await expect(save).toBeEnabled();
    await page.locator(".workspace-center").evaluate(element => { element.scrollTop = 0; });
    await expect(save).toBeInViewport();
    await save.click();
    await expect(page.getByText("Retention settings saved")).toBeVisible();
    expect(settings).toMatchObject({
      max_count: 32,
      max_bytes: 1024 ** 3,
      max_age_seconds: 86400,
    });
    await page.reload();
    await expect(page.getByLabel("Maximum screenshots")).toHaveValue("32");
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth + 1,
      ),
    ).toBeTruthy();
    expect(f.errors).toEqual([]);
  });
}

test("shared history handles a capture deleted after listing", async ({
  page,
}) => {
  const f = await fixture(page);
  await page.route("**/api/shares/share", (route) =>
    route.fulfill({
      json: {
        expires_at: "2026-10-08T00:00:00Z",
        artifacts: [],
        captures: [
          { capture_id: "gone", url: "/api/shares/share/captures/gone" },
        ],
      },
    }),
  );
  await page.route("**/api/shares/share/captures/gone", (route) =>
    route.fulfill({ status: 404, json: { detail: "Capture unavailable" } }),
  );
  await page.goto("/#/shares/share");
  await expect(page.getByText("Screenshot no longer available")).toBeVisible();
  await expect(
    page.getByRole("img", { name: "Selected shared surface" }),
  ).toHaveCount(0);
  expect(f.errors).toEqual([]);
});
