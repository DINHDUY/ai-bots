import { describe, it, expect, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { http, HttpResponse } from "msw";
import { server } from "../../support/server";
import { MacComputerSettings } from "../../../src/features/bots/MacComputerSettings";

describe("Mac computer settings", () => {
  it("pairs and binds the selected PC without submitting the bot form", async () => {
    const base = "http://127.0.0.1:8000";
    let saved: unknown;
    let assigned = false;
    const submit = vi.fn((event) => event.preventDefault());
    server.use(
      http.get(`${base}/api/capabilities`, () =>
        HttpResponse.json({ macos_computers: true }),
      ),
      http.get(`${base}/api/macos-computers`, () =>
        HttpResponse.json({
          computers: [
            {
              id: "pc-test",
              name: "My desktop",
              online: true,
              state: { ready: true, sharing: true, armed: false },
            },
          ],
        }),
      ),
      http.get(`${base}/api/bots/bot-test/compute-config`, () =>
        HttpResponse.json({ device_id: assigned ? "pc-test" : null, revision: assigned ? 5 : 4 }),
      ),
      http.post(
        `${base}/api/bots/bot-test/compute-config`,
        async ({ request }) => {
          saved = await request.json();
          assigned = true;
          return HttpResponse.json({ revision: 5 });
        },
      ),
      http.post(`${base}/api/macos-computers/enrollments`, () =>
        HttpResponse.json({
          code: "one-time-secret",
          expires_at: "2026-10-08T12:00:00Z",
        }),
      ),
    );
    render(
      <QueryClientProvider
        client={
          new QueryClient({ defaultOptions: { queries: { retry: false } } })
        }
      >
        <form onSubmit={submit}>
          <MacComputerSettings botId="bot-test" framework="open_interface" />
        </form>
      </QueryClientProvider>,
    );
    const user = userEvent.setup();
    await screen.findByText("My desktop · Control off");
    expect(screen.getByText("No Mac is assigned to this bot yet.")).toBeVisible();
    await user.selectOptions(
      screen.getByLabelText("Paired Mac"),
      "pc-test",
    );
    await user.click(screen.getByRole("button", { name: "Use this Mac" }));
    await waitFor(() =>
      expect(saved).toMatchObject({
        device_id: "pc-test",
        expected_revision: 4,
      }),
    );
    expect(await screen.findByText(/My desktop is assigned to this bot/)).toBeVisible();
    await user.click(screen.getByText("Pair a Mac"));
    expect(await screen.findByLabelText("One-time pairing code")).toHaveValue(
      "one-time-secret",
    );
    await user.click(screen.getByText("Hide code"));
    expect(screen.queryByLabelText("One-time pairing code")).toBeNull();
    expect(submit).not.toHaveBeenCalled();
  });

});
