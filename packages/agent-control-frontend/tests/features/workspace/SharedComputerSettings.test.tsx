import { fireEvent, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { http, HttpResponse } from "msw";
import { expect, it } from "vitest";
import { server } from "../../support/server";
import { SharedComputerSettings } from "../../../src/features/workspace/SharedComputerSettings";
import { WorkspaceHeader } from "../../../src/features/workspace/WorkspaceHeader";
import type { Bot } from "../../../src/api/client";
import { emptySession, type BotSession } from "../../../src/session/reduce";

const settings = () => ({
  mode: "per_bot" as "per_bot" | "shared",
  provider: "docker",
  profile_id: null,
  ownership: "attached" as const,
  revision: 0,
  role: "owner",
  limitation: "Overlapping runs share the desktop, browser, files, and processes.",
  attached_bot_ids: [] as string[],
  busy: false,
  computer: null,
});

function renderSettings(owner = true) {
  return render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <MemoryRouter>
        <SharedComputerSettings wid="space" owner={owner} />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

it("saves shared mode and shows the isolation warning", async () => {
  let saved = settings();
  server.use(
    http.get("*/api/workspaces/space/computer", () => HttpResponse.json(saved)),
    http.put("*/api/workspaces/space/computer", async ({ request }) => {
      const body = (await request.json()) as { mode: "per_bot" | "shared" };
      saved = { ...saved, mode: body.mode, revision: 1, attached_bot_ids: ["alpha", "beta"] };
      return HttpResponse.json(saved);
    }),
  );
  renderSettings();
  expect(await screen.findByText(/share the desktop/)).toBeInTheDocument();
  fireEvent.change(screen.getByLabelText("Computer mode"), { target: { value: "shared" } });
  expect(await screen.findByText("Workspace computer settings saved.")).toBeInTheDocument();
  expect(await screen.findByText(/2 attached bots/)).toBeInTheDocument();
  expect(saved.mode).toBe("shared");
});

it("names the shared computer in the workspace header", async () => {
  server.use(
    http.get("*/api/bots/orders/computer", () =>
      HttpResponse.json({
        workspace_computer: true,
        display_name: "Shared workspace computer",
        provider: "docker",
        computer: {
          id: "computer_1",
          generation: 1,
          status: "running",
          scope: "workspace",
          workspace_id: "space",
          attached_bot_ids: ["orders", "billing"],
        },
        capabilities: { lifecycle: false, remote_control: true, lifecycle_actions: [] },
      }),
    ),
    http.get("*/api/bots/orders/sessions/computer_1/control", () =>
      HttpResponse.json({ paused: false, lease: null }),
    ),
  );
  const bot: Bot = {
    id: "orders",
    name: "Orders",
    framework: "microsoft",
    instructions: "",
    credential_id: null,
    model: "gpt",
    created_at: "",
    updated_at: "",
  };
  const session: BotSession = { ...emptySession(), protocol: 2, connection: "connected" };
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <MemoryRouter>
        <WorkspaceHeader bot={bot} session={session} expanded onSettings={() => undefined} />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  expect(await screen.findByRole("heading", { name: "Shared workspace computer" })).toBeInTheDocument();
  expect(screen.getByText("Shared by 2 bots")).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Workspace computer settings" })).toHaveAttribute(
    "href",
    "/workspace?tab=computer&workspace=space",
  );
  expect(screen.queryByTitle("Hibernate computer")).not.toBeInTheDocument();
});
