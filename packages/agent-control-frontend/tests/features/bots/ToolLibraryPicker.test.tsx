import { useState } from "react";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { http, HttpResponse } from "msw";
import { it, expect } from "vitest";
import { server } from "../../support/server";
import type { Bot, ToolSelection, ToolSpec } from "../../../src/api/client";
import { ToolLibraryPicker } from "../../../src/features/bots/ToolLibraryPicker";
import { messagingTool } from "../../../src/features/workspace/channel";
import { CreateBotDialog } from "../../../src/features/bots/CreateBotDialog";
import { BotSettings } from "../../../src/features/bots/BotSettings";

const terminal: ToolSelection = { library_id: "sandbox.terminal", tool_id: "run_terminal_command", version: "1.0.0", configuration: {} };
const catalog: ToolSpec[] = [
  { library_id: "plugin.cli", tool_id: "list_dir", version: "1.0.0", configuration: {}, library_name: "CLI tools", name: "List directory", description: "List one workspace directory with ls.", compatible: true, reason: "", resource: null, bundle: false, provenance: "Installed CLI manifest" },
  { ...terminal, library_name: "Terminal", name: "Run command", description: "Run a shell command", compatible: true, reason: "", resource: null, bundle: false },
  { ...messagingTool, library_name: "Workspace collaboration", name: "Bot channel", description: "Exchange workspace messages", compatible: true, reason: "", resource: null, bundle: true },
  { library_id: "windows.desktop", tool_id: "windows_desktop", version: "1.0.0", configuration: {}, library_name: "Windows", name: "Desktop control", description: "Control Windows", compatible: false, reason: "Unavailable for this framework", resource: null, bundle: true },
];
const bot: Bot = { id: "tools", name: "General helper", framework: "microsoft", instructions: "Write concise answers", credential_id: "key", model: "test-model", created_at: "now", updated_at: "now" };
function wrap(child: React.ReactNode) {
  server.use(
    http.get("*/api/tool-libraries", () => HttpResponse.json({ libraries: catalog })),
    http.get("*/api/capabilities", () => HttpResponse.json({ tool_libraries: true, frameworks: ["microsoft", "anthropic"] })),
    http.get("*/api/credentials", () => HttpResponse.json([{ id: "key", provider: "openai", label: "Test key" }])),
  );
  return render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><MemoryRouter>{child}</MemoryRouter></QueryClientProvider>);
}

it("starts empty, offers compatible basics, and leaves collaboration optional", async () => {
  function Picker() {
    const [value, onChange] = useState<ToolSelection[]>([]);
    return <ToolLibraryPicker framework="microsoft" value={value} onChange={onChange} />;
  }
  wrap(<Picker />);
  const user = userEvent.setup();
  await screen.findByText("Terminal");
  expect(screen.getByText(/No tools selected/)).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "Computer basics" }));
  expect(screen.getByText(/1 selected · 1 configured/)).toBeInTheDocument();
  await user.click(screen.getByText("Workspace collaboration"));
  expect(screen.getByRole("checkbox", { name: "Bot channel (bundle)" })).not.toBeChecked();
  await user.click(screen.getByRole("checkbox", { name: "Bot channel (bundle)" }));
  await user.click(screen.getByRole("button", { name: "Clear" }));
  expect(screen.getByText(/No tools selected/)).toBeInTheDocument();
  await user.type(screen.getByRole("searchbox"), "Windows");
  expect(screen.getByRole("checkbox", { name: "Desktop control (bundle)" })).toBeDisabled();
});

it("shows an installed CLI tool and selects it", async () => {
  function Picker() {
    const [value, onChange] = useState<ToolSelection[]>([]);
    return <ToolLibraryPicker framework="microsoft" value={value} onChange={onChange} />;
  }
  wrap(<Picker />);
  const user = userEvent.setup();
  await user.click(await screen.findByText("CLI tools"));
  expect(screen.getByText("Installed CLI manifest")).toBeInTheDocument();
  await user.click(screen.getByRole("checkbox", { name: "List directory" }));
  expect(screen.getByText(/1 selected · 1 configured/)).toBeInTheDocument();
});

it("sends an explicit empty tool selection on creation", async () => {
  let submitted: Record<string, unknown> | undefined;
  server.use(http.post("*/api/bots", async ({ request }) => { submitted = await request.json() as Record<string, unknown>; return HttpResponse.json(bot); }));
  wrap(<CreateBotDialog open initialFramework="microsoft" onClose={() => {}} onCreated={() => {}} />);
  const user = userEvent.setup();
  await screen.findByRole("option", { name: "Test key" });
  await user.type(screen.getByRole("textbox", { name: "Name" }), "General helper");
  await user.click(screen.getByRole("button", { name: "Add bot" }));
  await waitFor(() => expect(submitted?.tool_selection).toEqual([]));
  expect(submitted?.instructions).toBe("");
});

it("keeps the draft on a stale revision and reloads only when requested", async () => {
  let submitted: Record<string, unknown> | undefined;
  let revision = 4;
  server.use(
    http.get("*/api/bots/tools/tools", () => HttpResponse.json({ tools_revision: revision, tool_selection: [terminal], bindings: [], editable: true, resources: { connector: [], skill: [] } })),
    http.patch("*/api/bots/tools", async ({ request }) => { submitted = await request.json() as Record<string, unknown>; revision = 5; return HttpResponse.json({ detail: { message: "Tools changed in another window. Reload and review your selection." } }, { status: 409 }); }),
  );
  wrap(<BotSettings bot={bot} />);
  const user = userEvent.setup();
  await screen.findByRole("button", { name: "Clear" });
  await user.click(screen.getByRole("button", { name: "Clear" }));
  await user.click(screen.getByRole("button", { name: "Save" }));
  await screen.findByRole("alert");
  expect(submitted).toMatchObject({ tool_selection: [], expected_tools_revision: 4, instructions: bot.instructions });
  expect(screen.getByText(/No tools selected/)).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "Reload saved tools" }));
  await screen.findByText(/1 selected · 1 configured/);
});
