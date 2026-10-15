import { test, expect } from "@playwright/test";
import { bots, fixture } from "./fixtures";

for (const width of [1600, 390]) {
  test(`tool selection saves and reopens at ${width}px`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 844 });
    const f = await fixture(page);
    const tool = { library_id: "sandbox.terminal", tool_id: "run_terminal_command", version: "1.0.0", configuration: {} };
    let selected: typeof tool[] = [];
    let revision = 1;
    let saved = { ...bots[0] };
    await page.route("**/api/capabilities", route => route.fulfill({ json: { protocol_version: 2, tool_libraries: true, frameworks: ["microsoft", "anthropic"] } }));
    await page.route("**/api/tool-libraries?*", route => route.fulfill({ json: { libraries: [{ ...tool, library_name: "Terminal", name: "Run command", description: "Run bounded commands on this bot's computer.", compatible: true, reason: "", resource: null, bundle: false }] } }));
    await page.route("**/api/bots/orders/tools", route => route.fulfill({ json: { tool_selection: selected, tools_revision: revision, bindings: [], resources: { connector: [], skill: [] }, editable: true } }));
    await page.route("**/api/bots/orders", async route => {
      if (route.request().method() === "PATCH") {
        const changes = route.request().postDataJSON();
        expect(changes.expected_tools_revision).toBe(revision);
        selected = changes.tool_selection;
        revision++;
        saved = { ...saved, ...changes };
      }
      return route.fulfill({ json: { ...saved, messages: [] } });
    });
    await page.reload();
    await page.getByRole("button", { name: "Bot settings", exact: true }).click();
    const dialog = page.getByRole("dialog", { name: "Bot settings" });
    await expect(dialog.getByText(/No tools selected/)).toBeVisible();
    await dialog.getByText("Terminal", { exact: true }).click();
    await dialog.getByRole("checkbox", { name: "Run command" }).check();
    const save = dialog.getByRole("button", { name: "Save", exact: true });
    await expect(save).toBeInViewport();
    expect(await dialog.evaluate(el => el.scrollWidth <= el.clientWidth)).toBe(true);
    await dialog.screenshot({ path: testInfo.outputPath("tool-settings.png") });
    await save.click();
    await expect(dialog).toHaveCount(0);
    expect(selected).toEqual([tool]);
    await page.getByRole("button", { name: "Bot settings", exact: true }).click();
    await dialog.getByText("Terminal · 1 selected", { exact: true }).click();
    await expect(dialog.getByRole("checkbox", { name: "Run command" })).toBeChecked();
    await dialog.getByRole("checkbox", { name: "Run command" }).uncheck();
    await save.click();
    await expect(dialog).toHaveCount(0);
    expect(selected).toEqual([]);
    expect(f.errors).toEqual([]);
  });
}
