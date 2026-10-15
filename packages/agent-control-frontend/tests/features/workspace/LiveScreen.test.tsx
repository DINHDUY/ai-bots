import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { expect, it } from "vitest";
import { server } from "../../support/server";
import { emptySession } from "../../../src/session/reduce";
import { useSessionStore } from "../../../src/session/store";
import { useWorkspaceUi } from "../../../src/session/workspaceUiStore";
import { LiveScreen } from "../../../src/features/workspace/LiveScreen";

it.each([
  { windows: true, surface: "desktop" },
  { windows: false, surface: "browser" },
])("requests the $surface surface for the first capture", async ({ windows, surface }) => {
  let requested: string | null = null;
  server.use(http.post("*/api/bots/bot-test/computer/capture", ({ request }) => {
    requested = new URL(request.url).searchParams.get("surface");
    return HttpResponse.json({ capture_id: "first-capture" });
  }));
  useSessionStore.setState({
    sessions: {
      "bot-test": {
        ...emptySession(),
        health: {
          health: "healthy", compatible: true, services: { desktop: true },
          observed_at: new Date().toISOString(),
        },
      },
    },
  });
  render(<LiveScreen botId="bot-test" shots={[]} dropped={0} historical={false} windows={windows} />);
  if (windows) {
    expect(screen.getByText(/select your paired PC and click Use this PC/)).toBeVisible();
  }
  await userEvent.click(screen.getByRole("button", { name: "Capture now" }));
  await waitFor(() => expect(requested).toBe(surface));
});


it("does not substitute the latest image for a deleted selected capture", async () => {
  useWorkspaceUi.getState().patch("selected-bot", { shotId: "deleted" });
  render(<LiveScreen botId="selected-bot" shots={[{ id: "latest", src: "/latest.png" }]} dropped={0} historical={false} />);
  expect(screen.getByText("Screenshot no longer available")).toBeVisible();
  expect(screen.queryByRole("img")).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "View latest" }));
  expect(screen.getByRole("img")).toHaveAttribute("src", "/latest.png");
});
