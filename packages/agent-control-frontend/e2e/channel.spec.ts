import { test, expect } from "@playwright/test";
import { fixture } from "./fixtures";
import { bots } from "./fixtures";

test("bot settings saves and reopens collaboration with its tool bundle", async ({
  page,
}) => {
  const f = await fixture(page);
  const tool = {
    library_id: "workspace.messaging",
    tool_id: "workspace_messaging",
    version: "1.0.0",
    configuration: {},
  };
  let selected: (typeof tool)[] = [],
    revision = 1;
  let collaboration = {
    bot_id: "orders",
    workspace_id: "space",
    name: "Orders ETL",
    purpose: "",
    state: "disabled",
    revision: 0,
    expires_at: null,
    published: 0,
  };
  await page.route("**/api/capabilities", (route) =>
    route.fulfill({
      json: {
        tool_libraries: true,
        workspace_bot_channels: true,
        frameworks: ["microsoft", "anthropic", "ufo"],
      },
    }),
  );
  await page.route("**/api/tool-libraries?*", (route) =>
    route.fulfill({
      json: {
        libraries: [
          {
            ...tool,
            library_name: "Workspace collaboration",
            name: "Bot channel",
            description: "Discover and message peers",
            compatible: true,
            reason: "",
            resource: null,
            bundle: true,
          },
        ],
      },
    }),
  );
  await page.route("**/api/bots/orders/tools", (route) =>
    route.fulfill({
      json: {
        tool_selection: selected,
        tools_revision: revision,
        bindings: [],
        resources: { connector: [], skill: [] },
        editable: true,
      },
    }),
  );
  await page.route("**/api/bots/orders/collaboration", (route) =>
    route.fulfill({ json: collaboration }),
  );
  await page.route("**/api/bots/orders/collaboration-task", (route) =>
    route.fulfill({ json: null }),
  );
  await page.route("**/api/bots/orders", async (route) => {
    if (route.request().method() === "PATCH") {
      const body = route.request().postDataJSON();
      expect(body.collaboration).toMatchObject({
        revision: 0,
        enabled: true,
        purpose: "Validate daily orders",
      });
      expect(body.expected_tools_revision).toBe(1);
      expect(body.tool_selection).toEqual([tool]);
      selected = body.tool_selection;
      revision++;
      collaboration = {
        ...collaboration,
        ...body.collaboration,
        revision: 1,
        state: "enabled",
        published: 1,
      };
    }
    return route.fulfill({
      json: {
        ...bots[0],
        messages: [],
        tool_selection: selected,
        tools_revision: revision,
      },
    });
  });
  await page.reload();
  await page.getByRole("button", { name: "Bot settings", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "Bot settings" });
  await dialog
    .getByRole("checkbox", { name: "Join workspace channel" })
    .check();
  await dialog
    .getByRole("textbox", { name: "Public purpose" })
    .fill("Validate daily orders");
  await dialog.getByRole("button", { name: "Save", exact: true }).click();
  await expect(dialog).toHaveCount(0);
  await page.getByRole("button", { name: "Bot settings", exact: true }).click();
  await expect(
    dialog.getByRole("checkbox", { name: "Join workspace channel" }),
  ).toBeChecked();
  await expect(
    dialog.getByRole("textbox", { name: "Public purpose" }),
  ).toHaveValue("Validate daily orders");
  expect(f.errors).toEqual([]);
});

for (const width of [1600, 390]) {
  test(`workspace bot channel at ${width}px`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 844 });
    const f = await fixture(page);
    const state = {
      workspace_id: "space",
      enabled: 1,
      revision: 2,
      seq: 3,
      role: "owner",
      enroll_future: false,
      owned_bots: [],
      directory: {
        bots: [
          {
            bot_id: "analyst",
            name: "Analyst",
            purpose: "Checks numbers and explains calculations.",
            state: "enabled",
            enrollment_id: "entry",
            capabilities: ["Workspace files"],
            availability: "ready",
            computer: "offline",
          },
        ],
        revision: 1,
        next_offset: null,
      },
      messages: [
        {
          id: "msg",
          thread_id: "thread",
          seq: 3,
          kind: "request",
          sender_name: "Writer",
          sender_bot_id: "writer",
          recipient_id: "analyst",
          body: "Please check the totals for this report.",
          created_at: "2026-10-07T09:42:00Z",
        },
      ],
      next_before: null,
      deliveries: [
        {
          id: "delivery",
          thread_id: "thread",
          message_id: "msg",
          target_bot_id: "analyst",
          state: "queued",
          reason: null,
          run_id: null,
        },
      ],
      threads: [
        {
          id: "thread",
          state: "waiting_peer",
          principal_id: "duy",
          runs_used: 1,
        },
      ],
    };
    await page.route("**/api/workspaces", (route) =>
      route.fulfill({ json: [{ id: "space", name: "Project workspace" }] }),
    );
    await page.route("**/api/preferences", (route) =>
      route.fulfill({ json: { workspace_id: "space" } }),
    );
    await page.route("**/api/workspaces/space/channel/snapshot", (route) =>
      route.fulfill({ json: state }),
    );
    await page.route("**/api/workspaces/space/channel/messages**", (route) =>
      route.fulfill({ json: { messages: state.messages, next_before: null } }),
    );
    await page.route(
      "**/api/workspaces/space/channel/threads/thread/cancel",
      (route) => {
        state.threads[0].state = "cancelled";
        state.deliveries[0].state = "cancelled";
        return route.fulfill({ json: { status: "cancelled" } });
      },
    );
    await page.routeWebSocket(
      "**/api/workspaces/space/channel/events/ws*",
      () => {},
    );
    await page.goto("/#/channel?workspace=space");
    await expect(
      page.getByRole("heading", { name: "Bot channel", exact: true }),
    ).toBeVisible();
    await expect(page.getByText("Writer → Analyst")).toBeVisible();
    await expect(page.getByText("Queued", { exact: true })).toBeVisible();
    await page
      .getByRole("button", { name: "View thread", exact: true })
      .click();
    await expect(
      page.getByRole("button", { name: "Stop thread" }),
    ).toBeVisible();
    expect(
      await page
        .locator(".channel-layout")
        .evaluate((el) => el.scrollWidth <= el.clientWidth),
    ).toBe(true);
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= window.innerWidth,
      ),
    ).toBe(true);
    await page.screenshot({
      path: testInfo.outputPath("bot-channel.png"),
      fullPage: true,
    });
    await page.getByRole("button", { name: "Stop thread" }).click();
    await expect(page.getByRole("button", { name: "Stop thread" })).toHaveCount(
      0,
    );
    expect(f.errors).toEqual([]);
  });
}
