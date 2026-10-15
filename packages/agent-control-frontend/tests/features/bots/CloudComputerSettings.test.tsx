import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { http, HttpResponse } from "msw";
import { it, expect, vi } from "vitest";
import { server } from "../../support/server";
import { CloudComputerSettings } from "../../../src/features/bots/CloudComputerSettings";
import { ComputerControls } from "../../../src/features/workspace/ComputerControls";

function wrap(child: React.ReactNode) {
  return render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>{child}</QueryClientProvider>);
}

it("saves the selected profile before attaching and treats 202 as progress", async () => {
  let config = { provider: "docker", profile_id: null as string | null, revision: 0, ownership: "attached", workspace_id: "workspace" };
  let attached: Record<string, unknown> | undefined;
  server.use(
    http.get("*/api/capabilities", () => HttpResponse.json({ cloud_computers: true })),
    http.get("*/api/bots/cloud/compute-config", () => HttpResponse.json(config)),
    http.get("*/api/workspaces/workspace/compute-profiles", () => HttpResponse.json({ profiles: [{ id: "ml", name: "Dedicated ML", provider: "azure_ml_compute_instance", resources: ["/approved/dedicated"], allowed_operations: ["attach"], region: "eastus", default_size: "Standard_DS3_v2", storage_policy: "persistent_host_disk" }] })),
    http.post("*/api/bots/cloud/compute-config", async ({ request }) => { config = { ...config, ...await request.json() as typeof config, revision: 1 }; return HttpResponse.json(config); }),
    http.get("*/api/bots/cloud/computer", () => HttpResponse.json({ computer: null })),
    http.post("*/api/bots/cloud/computer/attach", async ({ request }) => { attached = await request.json() as Record<string, unknown>; return HttpResponse.json({ status: "accepted" }, { status: 202 }); }),
  );
  wrap(<CloudComputerSettings botId="cloud" disabled={false} onSelection={vi.fn()} onBusyChange={vi.fn()} />);
  const user = userEvent.setup();
  await screen.findByRole("option", { name: "Azure ML Compute Instance" });
  await user.selectOptions(screen.getByLabelText("Computer provider"), "azure_ml_compute_instance");
  await user.selectOptions(screen.getByLabelText("Approved Azure computer"), "/approved/dedicated");
  await user.click(screen.getByRole("button", { name: "Attach computer" }));
  await screen.findByText(/Request accepted/);
  expect(config.provider).toBe("azure_ml_compute_instance");
  expect(attached).toMatchObject({ expected_revision: 1, generation: 0, resource_id: "/approved/dedicated" });
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
});

it("keeps Stop computer available offline and restores accepted progress", async () => {
  let stopped = false;
  server.use(
    http.get("*/api/capabilities", () => HttpResponse.json({ autopilot: false })),
    http.get("*/api/bots/cloud/computer", () => HttpResponse.json({
      provider: "azure_ml_compute_instance", display_name: "Azure ML · dedicated", computer: { id: "session", generation: 1, status: "running" },
      connectivity: "offline", power_state: "running", capabilities: { lifecycle: true, remote_control: false, lifecycle_actions: stopped ? [] : ["stop"] },
      operation: stopped ? { operation_id: "stop", operation: "stop", status: "accepted", phase: "polling", detail: "Waiting for Azure" } : null,
    })),
    http.get("*/api/bots/cloud/sessions/session/control", () => HttpResponse.json({ paused: false, lease: null })),
    http.post("*/api/bots/cloud/lifecycle/stop", () => { stopped = true; return HttpResponse.json({ status: "accepted" }, { status: 202 }); }),
  );
  wrap(<ComputerControls botId="cloud" />);
  const user = userEvent.setup();
  await user.click(await screen.findByRole("button", { name: "Stop computer" }));
  await user.click(screen.getByRole("button", { name: "Confirm stop" }));
  await screen.findByText(/Waiting for Azure/);
  expect(screen.queryByText("accepted", { exact: true })).not.toBeInTheDocument();
  await waitFor(() => expect(screen.queryByRole("alert")).not.toBeInTheDocument());
});
