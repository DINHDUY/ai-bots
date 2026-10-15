import { test, expect } from "@playwright/test";
import { bots, fixture } from "./fixtures";

for (const width of [1600, 390]) {
  test(`saving bot settings assigns the Windows PC and retains changes at ${width}px`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 844 });
    const f = await fixture(page);
    let saved = { ...bots[0], framework: "ufo" };
    const requests: unknown[] = [];
    const assignments: unknown[] = [];
    let config: { device_id: string | null; revision: number } = { device_id: null, revision: 0 };
    await page.route("**/api/capabilities", (route) => route.fulfill({ json: {
      protocol_version: 2, windows_computers: true, frameworks: ["anthropic", "microsoft", "ufo"],
    } }));
    await page.route("**/api/computers", (route) => route.fulfill({ json: { computers: [{
      id: "pc-test-1", name: "My Windows PC", online: true,
      state: { ready: true, sharing: true, armed: true },
    }] } }));
    await page.route("**/api/bots/orders/compute-config", async (route) => {
      if (route.request().method() === "POST") {
        const command = route.request().postDataJSON();
        assignments.push(command);
        config = { device_id: command.device_id, revision: config.revision + 1 };
      }
      return route.fulfill({ json: config });
    });
    await page.route("**/api/bots/orders", async (route) => {
      if (route.request().method() === "PATCH") {
        const changes = route.request().postDataJSON();
        requests.push(changes);
        saved = { ...saved, ...changes, updated_at: new Date().toISOString() };
        return route.fulfill({ json: saved });
      }
      return route.fulfill({ json: { ...saved, messages: [] } });
    });
    await page.reload();
    await expect(page.getByRole("button", { name: "Default Prompt", exact: true })).toHaveCount(0);
    await expect(page.getByRole("button", { name: "ETL prompt", exact: true })).toHaveCount(0);
    const settings = page.getByRole("button", { name: "Bot settings", exact: true });
    await settings.click();
    const dialog = page.getByRole("dialog", { name: "Bot settings" });
    const actions = dialog.getByRole("group", { name: "Bot settings actions" });
    await expect(actions.getByRole("button", { name: "Save", exact: true })).toBeInViewport();
    const detailsBox = await dialog.getByRole("region", { name: "Bot details and prompts" }).boundingBox();
    const computerBox = await dialog.getByRole("region", { name: "Computer and approvals" }).boundingBox();
    if (width > 1000) {
      expect(computerBox!.x).toBeGreaterThan(detailsBox!.x + detailsBox!.width);
      expect(computerBox!.y).toBe(detailsBox!.y);
    } else {
      expect(computerBox!.x).toBe(detailsBox!.x);
      expect(computerBox!.y).toBeGreaterThan(detailsBox!.y + detailsBox!.height);
    }
    const footerBefore = await actions.boundingBox();
    const fields = dialog.getByRole("region", { name: "Bot settings fields" });
    await fields.evaluate(element => { element.scrollTop = element.scrollHeight; });
    const footerAfter = await actions.boundingBox();
    expect(footerAfter!.y).toBe(footerBefore!.y);
    await expect(actions.getByRole("button", { name: "Delete", exact: true })).toBeInViewport();
    expect(await dialog.evaluate(element => element.scrollWidth <= element.clientWidth)).toBe(true);
    await fields.evaluate(element => { element.scrollTop = 0; });
    await dialog.screenshot({ path: testInfo.outputPath("bot-settings.png") });
    await dialog.getByLabel("Paired Windows computer").selectOption("pc-test-1");
    await expect(dialog.getByText(/PC selection not saved/)).toBeVisible();
    await dialog.getByLabel("Name", { exact: true }).fill("Updated Orders");
    await dialog.getByLabel("Model", { exact: true }).fill("");
    await dialog.getByRole("button", { name: "Save", exact: true }).click();
    await expect(dialog.getByText("Enter a model.")).toBeVisible();
    expect(requests).toHaveLength(0);
    await dialog.getByLabel("Model", { exact: true }).fill("gpt-4.1-mini");
    await dialog.getByRole("textbox", { name: "Instructions", exact: true }).fill("Updated instructions.");
    const prompt = "Summarize today's updates.\nList next steps.";
    await dialog.getByRole("textbox", { name: "Default Prompt (optional)", exact: true }).fill(prompt);
    await dialog.getByRole("button", { name: "Save", exact: true }).click();
    await expect(dialog).toHaveCount(0);
    expect(requests).toEqual([{
      name: "Updated Orders", model: "gpt-4.1-mini", credential_id: "key",
      instructions: "Updated instructions.",
      default_prompt: prompt,
    }]);
    expect(assignments).toHaveLength(1);
    expect(assignments[0]).toMatchObject({ device_id: "pc-test-1", expected_revision: 0 });
    await expect(page.getByRole("heading", { name: "Updated Orders", level: 1 })).toBeVisible();
    await expect(settings).toBeFocused();
    await page.getByRole("button", { name: "Default Prompt", exact: true }).click();
    await expect(page.getByRole("textbox", { name: "Message", exact: true })).toHaveValue(prompt);
    expect(f.sent).toHaveLength(0);
    await page.reload();
    await expect(page.getByRole("button", { name: "Default Prompt", exact: true })).toBeVisible();
    await settings.click();
    await expect(dialog.getByLabel("Name", { exact: true })).toHaveValue("Updated Orders");
    await expect(dialog.getByLabel("Model", { exact: true })).toHaveValue("gpt-4.1-mini");
    await expect(dialog.getByRole("textbox", { name: "Instructions", exact: true })).toHaveValue("Updated instructions.");
    await expect(dialog.getByLabel("Paired Windows computer")).toHaveValue("pc-test-1");
    const defaultPrompt = dialog.getByRole("textbox", { name: "Default Prompt (optional)", exact: true });
    await expect(defaultPrompt).toHaveValue(prompt);
    await defaultPrompt.fill(" \n\t ");
    await dialog.getByRole("button", { name: "Save", exact: true }).click();
    await expect(dialog).toHaveCount(0);
    await expect(page.getByRole("button", { name: "Default Prompt", exact: true })).toHaveCount(0);
    expect(f.errors).toEqual([]);
  });
}
