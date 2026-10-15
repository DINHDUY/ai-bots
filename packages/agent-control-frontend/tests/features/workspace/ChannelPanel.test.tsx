import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { http, HttpResponse } from "msw";
import { expect, it } from "vitest";
import { server } from "../../support/server";
import { FakeWebSocket } from "../../support/fakeSocket";
import { ChannelPanel, CollaborationSettings } from "../../../src/features/workspace/ChannelPanel";
import type { ChannelSnapshot } from "../../../src/features/workspace/channel";

const snapshot = (): ChannelSnapshot => ({
  workspace_id: "space",
  enabled: 1,
  revision: 2,
  seq: 3,
  role: "owner",
  enroll_future: false,
  owned_bots: [
    {
      bot_id: "writer",
      workspace_id: "space",
      name: "Writer",
      purpose: "Draft messages",
      state: "disabled",
      revision: 0,
      expires_at: null,
      published: 0,
    },
  ],
  directory: {
    bots: [
      {
        bot_id: "analyst",
        workspace_id: "space",
        name: "Analyst",
        purpose: "Check calculations",
        state: "enabled",
        revision: 1,
        expires_at: null,
        published: 1,
        enrollment_id: "enrollment",
        capabilities: [],
        availability: "ready",
        computer: "offline",
      },
    ],
    revision: 1,
    next_offset: null,
  },
  messages: [
    {
      id: "message",
      thread_id: "thread",
      seq: 3,
      kind: "request",
      sender_name: "Writer",
      sender_bot_id: "writer",
      recipient_id: "analyst",
      reply_to: null,
      body: "Check the total.",
      created_at: "2026-10-09T14:00:00Z",
    },
  ],
  next_before: null,
  deliveries: [
    {
      id: "delivery",
      thread_id: "thread",
      message_id: "message",
      target_bot_id: "analyst",
      state: "queued",
      reason: null,
      run_id: null,
      mode: "communication",
    },
  ],
  threads: [
    {
      id: "thread",
      state: "waiting_peer",
      principal_id: "user",
      runs_used: 1,
      deadline: "2026-10-09T14:30:00Z",
    },
  ],
});
function renderPanel(child: React.ReactNode) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  server.use(
    http.get("*/api/me", () =>
      HttpResponse.json({ id: "user", username: "Owner" }),
    ),
  );
  return {
    client,
    ...render(
      <QueryClientProvider client={client}>
        <MemoryRouter>{child}</MemoryRouter>
      </QueryClientProvider>,
    ),
  };
}

it("shows delivery state and deduplicates replayed membership updates", async () => {
  const state = snapshot();
  server.use(
    http.get("*/api/workspaces/space/channel/snapshot", () =>
      HttpResponse.json(state),
    ),
  );
  renderPanel(<ChannelPanel wid="space" />);
  await screen.findByText("Writer → Analyst");
  expect(screen.getByText("Queued")).toBeInTheDocument();
  expect(
    screen.queryByRole("link", { name: "View bot run" }),
  ).not.toBeInTheDocument();
  await waitFor(() => expect(FakeWebSocket.instances.length).toBe(1));
  const event = {
    seq: 4,
    kind: "bot.joined",
    data: { name: "Research", state: "enabled" },
  };
  act(() => {
    FakeWebSocket.instances[0].receive({ events: [event], next_seq: 4 });
    FakeWebSocket.instances[0].receive({ events: [event], next_seq: 4 });
  });
  await screen.findByText("Membership updates (1)");
});

it("keeps a failed task draft and retries with the same request ID", async () => {
  const requests: { request_id: string }[] = [];
  server.use(
    http.get("*/api/workspaces/space/channel/snapshot", () =>
      HttpResponse.json(snapshot()),
    ),
    http.post(
      "*/api/workspaces/space/channel/messages",
      async ({ request }) => {
        requests.push((await request.json()) as { request_id: string });
        return HttpResponse.json(
          { detail: "Connection lost" },
          { status: 503 },
        );
      },
    ),
  );
  renderPanel(<ChannelPanel wid="space" />);
  const user = userEvent.setup();
  await screen.findByText("Check the total.");
  await user.selectOptions(screen.getByLabelText("Recipient"), "analyst");
  await user.type(screen.getByLabelText("Task"), "Check my numbers");
  await user.click(screen.getByRole("button", { name: "Send task" }));
  await screen.findByRole("alert");
  expect(screen.getByLabelText("Task")).toHaveValue("Check my numbers");
  await user.click(screen.getByRole("button", { name: "Send task" }));
  await waitFor(() => expect(requests).toHaveLength(2));
  expect(requests[0].request_id).toBe(requests[1].request_id);
});

it("preserves enrollment choices after a stale configuration response", async () => {
  const state = snapshot();
  let submitted: unknown;
  server.use(
    http.get("*/api/workspaces/space/channel", () => HttpResponse.json(state)),
    http.patch("*/api/workspaces/space/channel", async ({ request }) => {
      submitted = await request.json();
      return HttpResponse.json(
        { detail: "Channel settings changed. Reload and review your draft." },
        { status: 409 },
      );
    }),
  );
  renderPanel(<CollaborationSettings wid="space" />);
  const user = userEvent.setup();
  await screen.findByRole("checkbox", { name: /Writer/ });
  await user.click(screen.getByRole("checkbox", { name: /Writer/ }));
  await user.click(
    screen.getByRole("checkbox", {
      name: "Select collaboration for my new bots",
    }),
  );
  await user.click(screen.getByRole("button", { name: "Save collaboration" }));
  await screen.findByRole("alert");
  expect(submitted).toMatchObject({
    revision: 2,
    enroll_bot_ids: ["writer"],
    enroll_future: true,
  });
  expect(screen.getByRole("checkbox", { name: /Writer/ })).toBeChecked();
  await user.click(
    screen.getByRole("button", { name: "Reload saved settings" }),
  );
  await waitFor(() =>
    expect(screen.getByRole("checkbox", { name: /Writer/ })).not.toBeChecked(),
  );
});

it("hides cached channel content when workspace access is revoked", async () => {
  let revoked = false;
  server.use(
    http.get("*/api/workspaces/space/channel/snapshot", () =>
      revoked
        ? HttpResponse.json(
            { detail: "Workspace unavailable" },
            { status: 404 },
          )
        : HttpResponse.json(snapshot()),
    ),
  );
  const { client } = renderPanel(<ChannelPanel wid="space" />);
  await screen.findByText("Check the total.");
  revoked = true;
  await act(() => client.invalidateQueries({ queryKey: ["channel", "space"] }));
  await screen.findByRole("alert");
  expect(screen.queryByText("Check the total.")).not.toBeInTheDocument();
});
