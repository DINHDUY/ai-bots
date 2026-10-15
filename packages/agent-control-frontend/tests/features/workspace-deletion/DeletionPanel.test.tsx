import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { http, HttpResponse } from "msw";
import { beforeEach, expect, it, vi } from "vitest";
import { server } from "../../support/server";
import { DeletionPanel } from "../../../src/features/workspace-deletion/DeletionPanel";
import type { DeleteCommand, DeletionPreview, DeletionResult } from "../../../src/api/deletions.generated";

const workspace = { id: "team", name: "Research team", role: "owner" };
const preview: DeletionPreview = { workspace_id: "team", workspace_name: workspace.name, bots: [{ id: "writer", name: "Writer" }], counts: { bots: 1, messages: 4 }, blockers: [], retained: [], preview_digest: "a".repeat(64) };
const result: DeletionResult = { workspace_id: "team", workspace_name: workspace.name, request_id: "delete_01", deleted_at: "2026-10-12T12:00:00Z", counts: { bots: 1 }, retained: [], cleanup: { state: "pending", remaining: 1, bytes_remaining: 10, errors: [] } };
let commands: DeleteCommand[];
beforeEach(() => {
  sessionStorage.clear(); commands = [];
  server.use(
    http.get("*/api/workspaces/team/deletion-preview", () => HttpResponse.json(preview)),
    http.get("*/api/workspace-deletions", () => HttpResponse.json({ items: [], next_cursor: null })),
    http.post("*/api/workspaces/team/deletions", async ({ request }) => {
      commands.push(await request.json() as DeleteCommand);
      return HttpResponse.json(result, { status: 202 });
    }),
  );
});
function show(value = workspace) {
  const onDeleted = vi.fn();
  return { onDeleted, ...render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
    <MemoryRouter><DeletionPanel workspace={value} onDeleted={onDeleted} /></MemoryRouter>
  </QueryClientProvider>) };
}
async function confirm() {
  fireEvent.click(screen.getByText("Delete workspace", { selector: "summary" }));
  fireEvent.click(screen.getByRole("button", { name: "Delete workspace" }));
  const dialog = screen.getByRole("dialog");
  await within(dialog).findByText("Writer");
  return within(dialog);
}
it("requires an exact confirmation and reports pending physical cleanup", async () => {
  const { onDeleted } = show();
  const dialog = await confirm();
  expect(dialog.getByRole("button", { name: "Delete workspace and contents" })).toBeDisabled();
  fireEvent.change(dialog.getByLabelText("Type the workspace name to confirm"), { target: { value: workspace.name } });
  fireEvent.click(dialog.getByRole("button", { name: "Delete workspace and contents" }));
  await screen.findByText("Workspace deleted; file cleanup pending.");
  expect(commands).toHaveLength(1);
  expect(commands[0].confirm_name).toBe(workspace.name);
  expect(onDeleted).toHaveBeenCalledOnce();
});
it("blocks active computers even after entering the correct name", async () => {
  server.use(http.get("*/api/workspaces/team/deletion-preview", () => HttpResponse.json({ ...preview, blockers: [{ code: "computers_active", message: "Close the shared computer.", url: "/workspace?tab=computer" }] })));
  show(); const dialog = await confirm();
  fireEvent.change(dialog.getByLabelText("Type the workspace name to confirm"), { target: { value: workspace.name } });
  expect(dialog.getByRole("button", { name: "Delete workspace and contents" })).toBeDisabled();
  expect(dialog.getByRole("link", { name: "Open controls" })).toHaveAttribute("href", "/workspace?tab=computer");
  expect(commands).toHaveLength(0);
});
it("recovers a lost response after reload without another deletion", async () => {
  server.use(http.post("*/api/workspaces/team/deletions", async ({ request }) => {
    commands.push(await request.json() as DeleteCommand); return HttpResponse.error();
  }), http.get("*/api/workspace-deletions/:id", () => HttpResponse.json(result)));
  const view = show(); const dialog = await confirm();
  fireEvent.change(dialog.getByLabelText("Type the workspace name to confirm"), { target: { value: workspace.name } });
  fireEvent.click(dialog.getByRole("button", { name: "Delete workspace and contents" }));
  await waitFor(() => expect(commands).toHaveLength(1));
  await waitFor(() => expect(screen.getAllByText(/Deletion result is unknown/).length).toBeGreaterThan(0));
  view.unmount(); show();
  fireEvent.click(screen.getByText("Delete workspace", { selector: "summary" }));
  fireEvent.click(screen.getByRole("button", { name: "Check deletion status" }));
  await screen.findByText("Workspace deleted; file cleanup pending.");
  expect(commands).toHaveLength(1);
});
it("protects Personal workspace and hides deletion from viewers", () => {
  const view = show({ id: "personal_user", name: "Personal workspace", role: "owner" });
  fireEvent.click(screen.getByText("Delete workspace", { selector: "summary" }));
  expect(screen.getByText("The Personal workspace cannot be deleted.")).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Delete workspace" })).toBeNull();
  view.unmount(); show({ ...workspace, role: "viewer" });
  fireEvent.click(screen.getByText("Delete workspace", { selector: "summary" }));
  expect(screen.queryByRole("button", { name: "Delete workspace" })).toBeNull();
});

it("shows an HTTP failure from a plain-text response and retries the same request", async () => {
  server.use(http.post("*/api/workspaces/team/deletions", async ({ request }) => {
    commands.push(await request.json() as DeleteCommand);
    return commands.length === 1 ? new HttpResponse("Internal Server Error", { status: 500 }) : HttpResponse.json(result);
  }));
  show(); const dialog = await confirm();
  fireEvent.change(dialog.getByLabelText("Type the workspace name to confirm"), { target: { value: workspace.name } });
  fireEvent.click(dialog.getByRole("button", { name: "Delete workspace and contents" }));
  await dialog.findByText(/HTTP 500/);
  expect(sessionStorage.getItem("workspace-deletion-pending")).toContain(commands[0].request_id);
  fireEvent.click(screen.getByRole("button", { name: "Retry original deletion" }));
  await screen.findByText("Workspace deleted; file cleanup pending.");
  expect(commands).toHaveLength(2);
  expect(commands[1]).toEqual(commands[0]);
});

it("reports a definite authorization rejection without retaining an unknown request", async () => {
  server.use(http.post("*/api/workspaces/team/deletions", () => HttpResponse.json({ detail: "Sign in required." }, { status: 401 })));
  show(); const dialog = await confirm();
  fireEvent.change(dialog.getByLabelText("Type the workspace name to confirm"), { target: { value: workspace.name } });
  fireEvent.click(dialog.getByRole("button", { name: "Delete workspace and contents" }));
  await dialog.findByText(/Sign in required/);
  expect(screen.queryByRole("button", { name: "Retry original deletion" })).not.toBeInTheDocument();
  expect(sessionStorage.getItem("workspace-deletion-pending")).toBeNull();
});
