import { describe, it, expect, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { http, HttpResponse } from "msw";
import { MemoryRouter } from "react-router-dom";
import { server } from "../../support/server";
import { BotSettings } from "../../../src/features/bots/BotSettings";
import { WindowsComputerSettings } from "../../../src/features/bots/WindowsComputerSettings";
import { windowsStatus } from "../../../src/features/bots/windowsStatus";

describe("Windows computer settings", () => {
  it("distinguishes connectivity, sharing and local control", () => {
    const pc = {
      id: "pc-1",
      name: "My PC",
      online: false,
      state: { ready: true, sharing: false, armed: false, reason: "" },
    };
    expect(windowsStatus(pc)).toBe("Offline");
    pc.online = true;
    expect(windowsStatus(pc)).toBe("Sharing off");
    pc.state.sharing = true;
    expect(windowsStatus(pc)).toBe("Control off");
    pc.state.armed = true;
    expect(windowsStatus(pc)).toBe("Ready");
  });
  it("pairs and binds the selected PC without submitting the bot form", async () => {
    const base = "http://127.0.0.1:8000";
    let saved: unknown;
    let assigned = false;
    const submit = vi.fn((event) => event.preventDefault());
    server.use(
      http.get(`${base}/api/capabilities`, () =>
        HttpResponse.json({ windows_computers: true }),
      ),
      http.get(`${base}/api/computers`, () =>
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
      http.post(`${base}/api/computers/enrollments`, () =>
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
          <WindowsComputerSettings botId="bot-test" framework="ufo" />
        </form>
      </QueryClientProvider>,
    );
    const user = userEvent.setup();
    await screen.findByText("My desktop · Control off");
    expect(screen.getByText("No Windows PC is assigned to this bot yet.")).toBeVisible();
    await user.selectOptions(
      screen.getByLabelText("Paired Windows computer"),
      "pc-test",
    );
    await user.click(screen.getByRole("button", { name: "Use this PC" }));
    await waitFor(() =>
      expect(saved).toMatchObject({
        device_id: "pc-test",
        expected_revision: 4,
      }),
    );
    expect(await screen.findByText(/My desktop is assigned to this bot/)).toBeVisible();
    await user.click(screen.getByText("Pair a Windows PC"));
    expect(await screen.findByLabelText("One-time pairing code")).toHaveValue(
      "one-time-secret",
    );
    await user.click(screen.getByText("Hide code"));
    expect(screen.queryByLabelText("One-time pairing code")).toBeNull();
    expect(submit).not.toHaveBeenCalled();
  });

  it.each(["microsoft", "anthropic"])(
    "exposes pairing in %s Bot Settings without attempting a Windows binding",
    async (framework) => {
      const configRequest = vi.fn(() => HttpResponse.json({ revision: 0 }));
      const saveBot = vi.fn(() => HttpResponse.json({}));
      server.use(
        http.get("*/api/capabilities", () =>
          HttpResponse.json({ windows_computers: true }),
        ),
        http.get("*/api/computers", () =>
          HttpResponse.json({ computers: [{ id: "pc-test", name: "My desktop", online: true, state: null }] }),
        ),
        http.get("*/api/credentials", () =>
          HttpResponse.json([{ id: "key", label: "Model key", provider: framework === "anthropic" ? "anthropic" : "openai" }]),
        ),
        http.all("*/api/bots/bot-test/compute-config", configRequest),
        http.patch("*/api/bots/bot-test", saveBot),
        http.post("*/api/computers/enrollments", () =>
          HttpResponse.json({
            code: "new-pairing-code",
            expires_at: "2026-10-08T12:00:00Z",
          }),
        ),
      );
      render(
        <QueryClientProvider
          client={new QueryClient({
            defaultOptions: { queries: { retry: false } },
          })}
        >
          <MemoryRouter>
            <BotSettings
              bot={{
                id: "bot-test",
                name: "Existing bot",
                framework,
                instructions: "",
                credential_id: "key",
                model: "test-model",
                created_at: "2026-10-08T00:00:00Z",
                updated_at: "2026-10-08T00:00:00Z",
              }}
            />
          </MemoryRouter>
        </QueryClientProvider>,
      );
      const pair = screen.getByRole("button", { name: "Pair a Windows PC" });
      await waitFor(() => expect(pair).toBeEnabled());
      expect(
        screen.getByText(/To control a paired PC, create a new bot/),
      ).toBeVisible();
      expect(screen.queryByRole("button", { name: "Use this PC" })).toBeNull();
      await userEvent.click(pair);
      expect(await screen.findByLabelText("One-time pairing code")).toHaveValue(
        "new-pairing-code",
      );
      await userEvent.selectOptions(screen.getByLabelText("Paired Windows computer"), "pc-test");
      await userEvent.click(screen.getByRole("button", { name: "Save" }));
      expect(await screen.findByText(/This bot cannot use a Windows PC/)).toHaveAttribute("role", "alert");
      expect(configRequest).not.toHaveBeenCalled();
      expect(saveBot).not.toHaveBeenCalled();
    },
  );

  it.each([200, 404])(
    "keeps pairing discoverable for an older backend (%s) and supports retry",
    async (status) => {
      server.use(
        http.get("*/api/capabilities", () => HttpResponse.json({}, { status })),
      );
      render(
        <QueryClientProvider
          client={new QueryClient({
            defaultOptions: { queries: { retry: false } },
          })}
        >
          <MemoryRouter>
            <WindowsComputerSettings botId="bot-test" framework="microsoft" />
          </MemoryRouter>
        </QueryClientProvider>,
      );
      await screen.findByText(
        /Restart the updated control backend to enable Windows pairing/,
      );
      const pair = screen.getByRole("button", { name: "Pair a Windows PC" });
      expect(pair).toBeVisible();
      expect(pair).toBeDisabled();
      server.use(
        http.get("*/api/capabilities", () =>
          HttpResponse.json({ windows_computers: true }),
        ),
        http.get("*/api/computers", () => HttpResponse.json({ computers: [] })),
      );
      await userEvent.click(
        screen.getByRole("button", { name: "Retry Windows pairing" }),
      );
      await waitFor(() => expect(pair).toBeEnabled());
    },
  );

  it("Save assigns the selected PC, preserves the selection on conflict, and skips unchanged bindings", async () => {
    const onSaved = vi.fn();
    let config: { device_id: string | null; revision: number } = { device_id: null, revision: 4 };
    const assignments: unknown[] = [];
    const bot = {
      id: "bot-test", name: "Windows assistant", framework: "ufo",
      model: "gpt-4.1", credential_id: "key", instructions: "",
      created_at: "2026-10-08T00:00:00Z", updated_at: "2026-10-08T00:00:00Z",
    };
    server.use(
      http.get("*/api/capabilities", () => HttpResponse.json({ windows_computers: true })),
      http.get("*/api/credentials", () => HttpResponse.json([{ id: "key", label: "Model key", provider: "openai" }])),
      http.get("*/api/computers", () => HttpResponse.json({ computers: [{
        id: "pc-test-1", name: "My desktop", online: true,
        state: { ready: true, sharing: true, armed: true },
      }] })),
      http.get("*/api/bots/bot-test/compute-config", () => HttpResponse.json(config)),
      http.patch("*/api/bots/bot-test", () => HttpResponse.json(bot)),
      http.post("*/api/bots/bot-test/compute-config", async ({ request }) => {
        assignments.push(await request.json());
        if (assignments.length === 1) {
          config = { device_id: null, revision: 5 };
          return HttpResponse.json({ detail: "Computer configuration changed" }, { status: 409 });
        }
        config = { device_id: "pc-test-1", revision: 6 };
        return HttpResponse.json(config);
      }),
    );
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(<QueryClientProvider client={client}><MemoryRouter>
      <BotSettings bot={bot} onSaved={onSaved} />
    </MemoryRouter></QueryClientProvider>);
    await screen.findByText("My desktop · Ready");
    await userEvent.selectOptions(screen.getByLabelText("Paired Windows computer"), "pc-test-1");
    expect(screen.getByText(/PC selection not saved/)).toBeVisible();
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Bot details saved, but the Windows PC was not assigned: Computer configuration changed");
    expect(onSaved).not.toHaveBeenCalled();
    expect(screen.getByLabelText("Paired Windows computer")).toHaveValue("pc-test-1");
    await waitFor(() => expect(client.getQueryData(["compute-config", bot.id])).toMatchObject({ revision: 5 }));
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(onSaved).toHaveBeenCalledTimes(1));
    expect(assignments).toMatchObject([
      { device_id: "pc-test-1", expected_revision: 4 },
      { device_id: "pc-test-1", expected_revision: 5 },
    ]);
    expect(screen.queryByText(/PC selection not saved/)).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(onSaved).toHaveBeenCalledTimes(2));
    expect(assignments).toHaveLength(2);
  });
});
