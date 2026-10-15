import { test, expect } from "@playwright/test";
import { fixture, summary } from "./fixtures";

test("workspace, expanded computer, and artifacts share one session", async ({
  page,
}, testInfo) => {
  const f = await fixture(page);
  await page
    .getByRole("textbox", { name: "Message", exact: true })
    .fill("Keep this draft while I inspect the computer.");
  await page.screenshot({ path: testInfo.outputPath("01-workspace.png") });
  const approval = page.getByRole("button", {
    name: "Allow once",
    exact: true,
  });
  await expect(approval).toBeInViewport();
  await page.getByRole("button", { name: "Expand cloud computer" }).click();
  await expect(
    page.getByRole("link", { name: "Review 1 approval", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("region", { name: "Terminal output" }),
  ).toBeVisible();
  await expect.poll(() => f.sockets.length).toBe(4);
  expect(f.sent).toHaveLength(0);
  await page.screenshot({ path: testInfo.outputPath("02-computer.png") });
  await page.getByRole("link", { name: "Workspace", exact: true }).click();
  await expect(
    page.getByRole("textbox", { name: "Message", exact: true }),
  ).toHaveValue("Keep this draft while I inspect the computer.");
  await approval.click();
  await expect.poll(() => f.sent.length).toBe(1);
  expect(f.sent[0]).toEqual({
    socket: 0,
    frame: { path: "/api/bots/orders/approvals/approve-etl/decision", decision: "approve", revision: 1, request_id: expect.any(String) },
  });
  await expect(page.getByText(/Accepted by the server/)).toBeVisible();
  await f.completed();
  await page.getByRole("button", { name: "Expand cloud computer" }).click();
  await page.getByRole("tab", { name: "Filesystem", exact: true }).click();
  await page
    .getByRole("button", { name: "2026-10-06.summary.json", exact: true })
    .click();
  await expect(page.getByText(summary, { exact: true })).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath("03-files.png") });
  await page.getByRole("button", { name: "azure.env", exact: true }).click();
  await expect(page.getByText("Configuration preview hidden")).toBeVisible();
  await expect(
    page.getByText("fixture-secret-never-show", { exact: false }),
  ).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Copy preview" })).toHaveCount(
    0,
  );
  await page.getByRole("tab", { name: "Activity", exact: true }).click();
  await page.goBack();
  await expect(
    page.getByRole("button", { name: "azure.env", exact: true }),
  ).toHaveAttribute("aria-pressed", "true");
  expect(f.errors).toEqual([]);
});

test("capture history stays selected as new captures arrive; tabs work by keyboard", async ({
  page,
}) => {
  const f = await fixture(page, "/#/bots/orders?view=computer&tab=screen");
  f.send({ event: "log", type: "SCREENSHOT_CAPTURE", payload: f.screenshot });
  await page.getByRole("button", { name: "Capture 1", exact: true }).click();
  f.send({ event: "log", type: "SCREENSHOT_CAPTURE", payload: f.screenshot });
  await expect(
    page.getByRole("button", { name: "Capture 1", exact: true }),
  ).toHaveAttribute("aria-pressed", "true");
  await page.getByRole("button", { name: "Back to latest" }).click();
  await expect(
    page.getByRole("button", { name: "Capture 3", exact: true }),
  ).toHaveAttribute("aria-pressed", "true");
  await page.getByRole("tab", { name: "Screen", exact: true }).focus();
  await page.keyboard.press("ArrowRight");
  await expect(
    page.getByRole("tab", { name: "Terminal", exact: true }),
  ).toBeFocused();
  await expect(
    page.getByRole("tab", { name: "Terminal", exact: true }),
  ).toHaveAttribute("aria-selected", "true");
  expect(f.sent).toHaveLength(0);
});

test("conversation follows new content only when the operator is at the bottom", async ({
  page,
}) => {
  const f = await fixture(page);
  const thread = page.getByLabel("Conversation messages", { exact: true });
  for (let i = 0; i < 25; i++) {
    f.send({
      event: "log",
      type: "RESULT",
      payload: `Observation ${i}: **Validated source rows.**\n\nThe source can now be inspected in the computer.`,
    });
  }
  await expect(
    thread.getByText("Observation 24:", { exact: false }),
  ).toBeVisible();
  const remaining = () =>
    thread.evaluate((el) => el.scrollHeight - el.clientHeight - el.scrollTop);
  await expect.poll(remaining).toBeLessThan(5);
  await thread.evaluate((el) => {
    el.scrollTop = 120;
    el.dispatchEvent(new Event("scroll"));
  });
  f.send({
    event: "log",
    type: "RESULT",
    payload:
      "A new validation result arrived while reviewing earlier messages.",
  });
  const jump = page.getByRole("button", { name: "New messages", exact: true });
  await expect(jump).toBeVisible();
  await expect.poll(() => thread.evaluate((el) => el.scrollTop)).toBe(120);
  await jump.click();
  await expect.poll(remaining).toBeLessThan(5);
  await expect(jump).toHaveCount(0);
  await thread.evaluate((el) => {
    el.scrollTop = 180;
    el.dispatchEvent(new Event("scroll"));
  });
  await page.getByRole("button", { name: "Expand cloud computer" }).click();
  await page.getByRole("link", { name: "Workspace", exact: true }).click();
  await expect.poll(() => thread.evaluate((el) => el.scrollTop)).toBe(180);
  expect(f.sent).toHaveLength(0);
  expect(f.errors).toEqual([]);
});

test("reconnect retains server-owned approval without sending a command", async ({ page }) => {
  const f = await fixture(page);
  f.sockets[0].close({ code: 1012, reason: "restart" });
  await expect.poll(() => f.sockets.length).toBe(5);
  expect(f.sent).toHaveLength(0);
  await expect(page.getByRole("button", { name: "Allow once", exact: true })).toBeVisible();
  expect(f.errors).toEqual([]);
});

test("native settings dialog restores focus; theme and sign-out work", async ({
  page,
}) => {
  const f = await fixture(page);
  const settings = page.getByRole("button", {
    name: "Bot settings",
    exact: true,
  });
  await settings.click();
  await expect(
    page.getByRole("dialog", { name: "Bot settings", exact: true }),
  ).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(settings).toBeFocused();
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await page.getByRole("button", { name: "Account menu" }).click();
  await page.getByRole("button", { name: "Light theme", exact: true }).click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
  await page.keyboard.press("Escape");
  await page
    .getByRole("textbox", { name: "Message", exact: true })
    .fill("private draft");
  await page.getByRole("button", { name: "Account menu" }).click();
  await page.getByRole("button", { name: "Sign out", exact: true }).click();
  // This fixture signs the same user back in. No prior session UI may survive.
  await expect(
    page.getByRole("textbox", { name: "Message", exact: true }),
  ).toHaveValue("");
  expect(f.errors).toEqual([]);
});

for (const size of [
  { width: 1366, height: 768 },
  { width: 1024, height: 768 },
  { width: 390, height: 844 },
]) {
  test(`responsive views at ${size.width}x${size.height}`, async ({
    page,
  }, testInfo) => {
    await page.setViewportSize(size);
    const f = await fixture(page);
    await expect(
      page.getByRole("button", { name: "Send", exact: true }),
    ).toBeInViewport();
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBe(true);
    await page
      .getByRole("button", { name: "Allow once", exact: true })
      .scrollIntoViewIfNeeded();
    await expect(
      page.getByRole("button", { name: "Allow once", exact: true }),
    ).toBeInViewport();
    await page.screenshot({ path: testInfo.outputPath("workspace.png") });
    if (size.width < 768)
      await page
        .getByRole("navigation", { name: "Mobile navigation" })
        .getByRole("link", { name: "Computer", exact: true })
        .click();
    else
      await page
        .getByRole("button", { name: "Open cloud computer", exact: true })
        .click();
    await expect(
      page.getByRole("tab", { name: "Screen", exact: true }),
    ).toBeInViewport();
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBe(true);
    await page.screenshot({ path: testInfo.outputPath("computer.png") });
    await f.completed();
    await page.getByRole("tab", { name: "Filesystem", exact: true }).click();
    await page
      .getByRole("button", { name: "2026-10-06.summary.json", exact: true })
      .click();
    await expect(page.getByText(summary, { exact: true })).toBeVisible();
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBe(true);
    await page.screenshot({ path: testInfo.outputPath("files.png") });
    expect(f.errors).toEqual([]);
  });
}
