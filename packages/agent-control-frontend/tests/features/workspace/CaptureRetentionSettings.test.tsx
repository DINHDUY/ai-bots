import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { http, HttpResponse } from "msw";
import { expect, it } from "vitest";
import { server } from "../../support/server";
import { CaptureRetentionSettings } from "../../../src/features/workspace/CaptureRetentionSettings";

const initial = () => ({
  revision: 1,
  role: "owner",
  max_count: null as number | null,
  max_bytes: null as number | null,
  max_age_seconds: 604800,
  reserve_percent: 25,
  cleanup_target_percent: 50,
  shared_limit_bytes: 2 * 1024 ** 3,
  cleanup_pending: false,
  last_cleanup_at: null,
  last_error: null,
  usage: {
    retained_count: 42,
    screenshot_bytes: 100,
    pending_bytes: 0,
    shared_bytes: 200,
  },
});
function renderSettings() {
  return render(
    <QueryClientProvider
      client={
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      }
    >
      <CaptureRetentionSettings wid="space" />
    </QueryClientProvider>,
  );
}
it("previews, saves and reopens combined retention settings", async () => {
  let saved = initial();
  server.use(
    http.get("*/api/workspaces/space/capture-retention", () =>
      HttpResponse.json(saved),
    ),
    http.post("*/api/workspaces/space/capture-retention/preview", () =>
      HttpResponse.json({ remove_count: 12, remove_bytes: 80 }),
    ),
    http.patch(
      "*/api/workspaces/space/capture-retention",
      async ({ request }) => {
        saved = {
          ...saved,
          ...((await request.json()) as object),
          revision: 2,
        };
        return HttpResponse.json(saved);
      },
    ),
  );
  const view = renderSettings();
  fireEvent.click(await screen.findByLabelText("Keep latest screenshots"));
  fireEvent.change(screen.getByLabelText("Maximum screenshots"), {
    target: { value: "30" },
  });
  fireEvent.click(screen.getByLabelText("Limit screenshot storage"));
  fireEvent.change(screen.getByLabelText("Retention period"), {
    target: { value: "86400" },
  });
  await waitFor(() =>
    expect(screen.getByRole("button", { name: "Save" })).toBeEnabled(),
  );
  expect(screen.getByText(/At 75%/)).toHaveTextContent("50%");
  fireEvent.click(screen.getByRole("button", { name: "Save" }));
  await screen.findByText("Retention settings saved");
  expect(saved).toMatchObject({
    max_count: 30,
    max_bytes: 1024 ** 3,
    max_age_seconds: 86400,
    reserve_percent: 25,
    cleanup_target_percent: 50,
  });
  view.unmount();
  renderSettings();
  await waitFor(() =>
    expect(screen.getByLabelText("Maximum screenshots")).toHaveValue(30),
  );
});

it("keeps an unsaved draft after a revision conflict", async () => {
  server.use(
    http.get("*/api/workspaces/space/capture-retention", () =>
      HttpResponse.json(initial()),
    ),
    http.post("*/api/workspaces/space/capture-retention/preview", () =>
      HttpResponse.json({ remove_count: 0, remove_bytes: 0 }),
    ),
    http.patch("*/api/workspaces/space/capture-retention", () =>
      HttpResponse.json(
        { detail: "Retention settings changed. Reload before saving." },
        { status: 409 },
      ),
    ),
  );
  renderSettings();
  fireEvent.click(await screen.findByLabelText("Keep latest screenshots"));
  fireEvent.change(screen.getByLabelText("Maximum screenshots"), {
    target: { value: "50" },
  });
  await waitFor(() =>
    expect(screen.getByRole("button", { name: "Save" })).toBeEnabled(),
  );
  fireEvent.click(screen.getByRole("button", { name: "Save" }));
  await screen.findByRole("alert");
  expect(screen.getByLabelText("Maximum screenshots")).toHaveValue(50);
});

it("shows retention as read only for a viewer", async () => {
  server.use(
    http.get("*/api/workspaces/space/capture-retention", () =>
      HttpResponse.json({ ...initial(), role: "viewer" }),
    ),
  );
  renderSettings();
  expect(
    await screen.findByLabelText("Keep latest screenshots"),
  ).toBeDisabled();
  expect(
    screen.queryByRole("button", { name: "Save" }),
  ).not.toBeInTheDocument();
});
