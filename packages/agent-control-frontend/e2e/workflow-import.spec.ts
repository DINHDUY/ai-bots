import { test, expect } from "@playwright/test";
import { fixture } from "./fixtures";
import type { ImportCommand, ImportDraft, ImportPreview, ImportResult } from "../src/api/imports.generated";

for (const width of [1600, 390]) {
  test(`import review and recovery at ${width}px`, async ({ page }) => {
    await fixture(page);
    await page.setViewportSize({ width, height: 1000 });
    const commands: ImportCommand[] = [];
    let receipt: ImportResult | null = null;
    await page.route("**/api/capabilities", route => route.fulfill({ json: { protocol_version: 2, workflow_imports: true } }));
    await page.route("**/api/workspaces", route => route.fulfill({ json: [{ id: "existing", name: "Existing", role: "owner" }, ...(receipt ? [{ id: receipt.workspace_id, name: receipt.workspace_name, role: "owner" }] : [])] }));
    await page.route("**/api/preferences", route => route.fulfill({ json: { revision: 1, workspace_id: "existing", onboarding: "completed" } }));
    await page.route("**/api/workflow-imports/preview", async route => {
      const source = route.request().postDataJSON() as ImportDraft;
      const response: ImportPreview = { workspace_name: source.workspace_name, valid: true, preview_digest: "a".repeat(64), errors: [], files: source.files.map(file => ({
        ...file, name: file.overrides?.name ?? file.filename.replace(".md", ""), purpose: file.overrides?.purpose ?? "",
        instructions: file.content.split("---\r\n").slice(2).join("---\r\n"), runtime: file.overrides?.runtime ?? source.defaults ?? {}, errors: [], warnings: ["Metadata has no configuration effect: tools"],
      })) };
      await route.fulfill({ json: response });
    });
    await page.route("**/api/workflow-imports", async route => {
      const command = route.request().postDataJSON() as ImportCommand;
      commands.push(command);
      receipt = { request_id: command.request_id, workspace_id: "imported", workspace_name: command.workspace_name, bots: command.files.map((file, index) => ({
        file_id: file.file_id, filename: file.filename, name: file.overrides?.name ?? file.filename.replace(".md", ""), bot_id: `imported_${index}`, source_hash: "hash", body_hash: "hash",
      })) };
      await route.abort("failed");
    });
    await page.route("**/api/workflow-imports/*", async route => {
      if (route.request().url().endsWith("/preview")) return route.fallback();
      await route.fulfill({ json: receipt });
    });
    await page.goto("/#/workspace");
    await page.getByRole("button", { name: "Import workflow", exact: true }).click();
    const dialog = page.getByRole("dialog", { name: "Import workflow" });
    await dialog.getByLabel("New workspace name").fill("Imported team");
    await dialog.getByLabel("Agent Markdown files").setInputFiles([
      { name: "Planner.md", mimeType: "text/markdown", buffer: Buffer.from("---\r\nname: Planner\r\ntools: [foreign]\r\n---\r\n\r\n# Plan\r\n  Keep spacing  \r\n") },
      { name: "Writer.md", mimeType: "text/markdown", buffer: Buffer.from("---\r\nname: Writer\r\n---\r\n# Write\r\n") },
    ]);
    await expect(dialog).toBeVisible();
    await dialog.getByRole("combobox", { name: "API key", exact: true }).selectOption("key");
    await dialog.getByRole("button", { name: "Preview agents" }).click();
    await expect(dialog.getByText("2 agents validated and ready to import.")).toBeVisible();
    const writer = dialog.getByRole("region", { name: "Writer.md" });
    await writer.getByLabel("Bot name", { exact: true }).fill("Editor");
    await writer.getByLabel("Public purpose").fill("Review drafts");
    await writer.getByLabel("Use different runtime settings for this bot").check();
    await writer.getByLabel("Model", { exact: true }).fill("gpt-4.1-mini");
    await expect(dialog.getByRole("button", { name: "Import workflow", exact: true })).toBeDisabled();
    await dialog.getByRole("button", { name: "Preview agents" }).click();
    await expect(dialog.getByText("2 agents validated and ready to import.")).toBeVisible();
    expect(await dialog.evaluate(element => element.scrollWidth <= element.clientWidth)).toBe(true);
    await dialog.getByRole("button", { name: "Import workflow", exact: true }).click();
    await expect(dialog.getByText(/import result is unknown/)).toBeVisible();
    expect(commands).toHaveLength(1);
    expect(commands[0].files[1].overrides?.runtime?.model).toBe("gpt-4.1-mini");
    expect(commands[0].files[0].content).toContain("\r\n  Keep spacing  \r\n");
    await page.reload();
    await page.getByRole("button", { name: "Import workflow", exact: true }).click();
    await dialog.getByRole("button", { name: "Check import result" }).click();
    await expect(dialog.getByText("Imported team is ready")).toBeVisible();
    await expect(dialog.getByRole("link", { name: "Editor", exact: true })).toBeVisible();
    await expect(dialog.getByRole("link", { name: "Open Bot channel" })).toHaveAttribute("href", "#/channel?workspace=imported");
    await expect(dialog.getByText(/shared computer has not been created/)).toBeVisible();
    expect(commands).toHaveLength(1);
  });
}
