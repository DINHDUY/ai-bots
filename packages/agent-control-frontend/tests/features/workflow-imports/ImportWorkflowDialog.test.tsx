import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { http, HttpResponse } from "msw";
import { beforeEach, expect, it, vi } from "vitest";
import { server } from "../../support/server";
import { ImportWorkflowDialog } from "../../../src/features/workflow-imports/ImportWorkflowDialog";
import type { ImportCommand, ImportDraft, ImportPreview, ImportResult } from "../../../src/api/imports.generated";

const result: ImportResult = { request_id: "request_123", workspace_id: "created", workspace_name: "New team", bots: [
  { file_id: "one", filename: "writer.md", name: "Writer", bot_id: "writer", source_hash: "hash", body_hash: "hash" },
] };
let commands: ImportCommand[];

beforeEach(() => {
  sessionStorage.clear();
  commands = [];
  server.use(
    http.get("*/api/workspaces", () => HttpResponse.json([{ id: result.workspace_id, name: result.workspace_name, role: "owner" }])),
    http.get("*/api/capabilities", () => HttpResponse.json({ workflow_imports: true })),
    http.get("*/api/credentials", () => HttpResponse.json([{ id: "key", provider: "openai", label: "Test key" }])),
    http.post("*/api/workflow-imports/preview", async ({ request }) => {
      const body = await request.json() as ImportDraft;
      const response: ImportPreview = { workspace_name: body.workspace_name, valid: true, preview_digest: "a".repeat(64), errors: [], files: body.files.map(file => ({
        ...file, name: file.overrides?.name ?? "Writer", purpose: file.overrides?.purpose ?? "Write drafts", instructions: "\nPreserve body  \n", runtime: file.overrides?.runtime ?? body.defaults ?? {}, errors: [], warnings: [],
      })) };
      return HttpResponse.json(response);
    }),
    http.post("*/api/workflow-imports", async ({ request }) => {
      commands.push(await request.json() as ImportCommand);
      return HttpResponse.json({ ...result, request_id: commands.at(-1)!.request_id }, { status: 201 });
    }),
  );
});

function show(onCreated = vi.fn().mockResolvedValue(undefined)) {
  return { onCreated, ...render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
    <MemoryRouter><ImportWorkflowDialog open onClose={() => undefined} onCreated={onCreated} /></MemoryRouter>
  </QueryClientProvider>) };
}

function file(name = "writer.md", content = "---\nname: Writer\n---\n\nPreserve body  \n") {
  const value = new File([content], name, { type: "text/markdown" });
  Object.defineProperty(value, "arrayBuffer", { value: async () => new TextEncoder().encode(content).buffer });
  return value;
}

async function review() {
  await waitFor(() => expect(screen.getByLabelText("New workspace name")).toBeEnabled());
  fireEvent.change(screen.getByLabelText("New workspace name"), { target: { value: "New team" } });
  fireEvent.change(screen.getByLabelText("Agent Markdown files"), { target: { files: [file()] } });
  await screen.findByRole("region", { name: "writer.md" });
  fireEvent.change(screen.getByLabelText("API key"), { target: { value: "key" } });
  fireEvent.click(screen.getByRole("button", { name: "Preview agents" }));
  await screen.findByText("1 agents validated and ready to import.");
}

it("reviews exact bodies and invalidates preview when names or purposes change", async () => {
  const { onCreated } = show();
  await review();
  expect(screen.getByText("Preserve body", { exact: false, selector: "pre" }).textContent).toBe("\nPreserve body  \n");
  fireEvent.change(screen.getByLabelText("Bot name"), { target: { value: "Editor" } });
  fireEvent.change(screen.getByLabelText("Public purpose"), { target: { value: "Review writing" } });
  expect(screen.getByRole("button", { name: "Import workflow" })).toBeDisabled();
  fireEvent.click(screen.getByRole("button", { name: "Preview agents" }));
  await waitFor(() => expect(screen.getByRole("button", { name: "Import workflow" })).toBeEnabled());
  fireEvent.click(screen.getByRole("button", { name: "Import workflow" }));
  await screen.findByText("New team is ready");
  expect(commands).toHaveLength(1);
  expect(commands[0].files[0].overrides).toEqual({ name: "Editor", purpose: "Review writing" });
  expect(commands[0].files[0].content).toContain("---\nname: Writer\n---");
  expect(onCreated).toHaveBeenCalledOnce();
  expect(screen.getByRole("link", { name: "Open Bot channel" })).toHaveAttribute("href", "/channel?workspace=created");
  expect(screen.getByText(/shared computer has not been created/)).toBeInTheDocument();
  expect(sessionStorage.getItem("workflow-import-request")).toBeNull();
});

it("keeps the same command when a response is lost", async () => {
  let calls = 0;
  server.use(http.post("*/api/workflow-imports", async ({ request }) => {
    commands.push(await request.json() as ImportCommand);
    if (++calls === 1) return HttpResponse.error();
    return HttpResponse.json(result, { status: 201 });
  }));
  show(); await review();
  fireEvent.click(screen.getByRole("button", { name: "Import workflow" }));
  await screen.findByText(/import result is unknown/);
  expect(screen.getByLabelText("Bot name")).toBeDisabled();
  fireEvent.click(screen.getByRole("button", { name: "Retry same import" }));
  await screen.findByText("New team is ready");
  expect(commands).toHaveLength(2);
  expect(commands[0]).toEqual(commands[1]);
});

it("recovers a receipt after reload without resubmitting files", async () => {
  sessionStorage.setItem("workflow-import-request", "request_123");
  server.use(http.get("*/api/workflow-imports/request_123", () => HttpResponse.json(result)));
  show();
  fireEvent.click(await screen.findByRole("button", { name: "Check import result" }));
  await screen.findByText("New team is ready");
  expect(commands).toHaveLength(0);
});

it("reports successful import even when selecting the workspace fails", async () => {
  show(vi.fn().mockRejectedValue(new Error("Preference conflict")));
  await review();
  fireEvent.click(screen.getByRole("button", { name: "Import workflow" }));
  await screen.findByText(/workspace was imported. Selecting it failed/);
  expect(screen.getByText("New team is ready")).toBeInTheDocument();
  expect(commands).toHaveLength(1);
});

it("retains invalid files for removal and offers key setup without losing the draft", async () => {
  server.use(http.get("*/api/credentials", () => HttpResponse.json([])));
  show();
  await waitFor(() => expect(screen.getByLabelText("Agent Markdown files")).toBeEnabled());
  fireEvent.change(screen.getByLabelText("Agent Markdown files"), { target: { files: [file("wrong.txt")] } });
  const card = await screen.findByRole("region", { name: "wrong.txt" });
  expect(await within(card).findByRole("alert")).toHaveTextContent("Markdown");
  expect(screen.getByRole("link", { name: "Add an API key in a new tab" })).toHaveAttribute("target", "_blank");
  fireEvent.click(within(card).getByRole("button", { name: "Remove" }));
  expect(screen.queryByRole("region", { name: "wrong.txt" })).not.toBeInTheDocument();
});

it("supports per-agent runtime overrides and rejects stale previews", async () => {
  show(); await review();
  fireEvent.click(screen.getByLabelText("Use different runtime settings for this bot"));
  const card = screen.getByRole("region", { name: "writer.md" });
  fireEvent.change(within(card).getByLabelText("Model"), { target: { value: "gpt-4.1-mini" } });
  fireEvent.click(screen.getByRole("button", { name: "Preview agents" }));
  await waitFor(() => expect(screen.getByRole("button", { name: "Import workflow" })).toBeEnabled());
  server.use(http.post("*/api/workflow-imports", () => HttpResponse.json({ detail: "Import preview changed." }, { status: 409 })));
  fireEvent.click(screen.getByRole("button", { name: "Import workflow" }));
  await screen.findByText(/Import preview changed/);
  expect(screen.getByRole("button", { name: "Import workflow" })).toBeDisabled();
  expect(within(card).getByLabelText("Model")).toHaveValue("gpt-4.1-mini");
});

it("shows a deleted import without selecting it or resubmitting", async () => {
  sessionStorage.setItem("workflow-import-request", result.request_id);
  server.use(http.get("*/api/workspaces", () => HttpResponse.json([])),
    http.get("*/api/workflow-imports/:id", () => HttpResponse.json(result)));
  const { onCreated } = show();
  fireEvent.click(await screen.findByRole("button", { name: "Check import result" }));
  await screen.findByText("This imported workspace was deleted");
  expect(onCreated).not.toHaveBeenCalled();
  expect(screen.queryByRole("link", { name: "Open Bot channel" })).toBeNull();
  expect(commands).toHaveLength(0);
});
