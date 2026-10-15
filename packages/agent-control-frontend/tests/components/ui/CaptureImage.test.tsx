import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { expect, it, vi } from "vitest";
import { server } from "../../support/server";
import { CaptureImage } from "../../../src/components/ui/CaptureImage";

it("hides a failed image and confirms absence once", async () => {
  let reads = 0;
  server.use(
    http.get("*/missing.png", () => {
      reads++;
      return new HttpResponse(null, { status: 404 });
    }),
  );
  const unavailable = vi.fn();
  render(
    <CaptureImage
      src="http://localhost/missing.png"
      alt="Capture"
      onUnavailable={unavailable}
    />,
  );
  fireEvent.error(screen.getByRole("img"));
  expect(screen.queryByRole("img")).not.toBeInTheDocument();
  await screen.findByText("Screenshot no longer available");
  expect(unavailable).toHaveBeenCalledOnce();
  expect(reads).toBe(1);
});

it("lets a temporary failure retry and resets failure for a new capture", async () => {
  server.use(
    http.get("*/offline.png", () => new HttpResponse(null, { status: 503 })),
  );
  const unavailable = vi.fn();
  const view = render(
    <CaptureImage
      src="http://localhost/offline.png"
      alt="Capture"
      onUnavailable={unavailable}
    />,
  );
  fireEvent.error(screen.getByRole("img"));
  fireEvent.click(await screen.findByRole("button", { name: "Retry" }));
  expect(screen.getByRole("img")).toBeVisible();
  fireEvent.error(screen.getByRole("img"));
  await screen.findByText("Screenshot could not be loaded");
  view.rerender(
    <CaptureImage src="http://localhost/new.png" alt="New capture" />,
  );
  await waitFor(() =>
    expect(screen.getByRole("img")).toHaveAttribute(
      "src",
      "http://localhost/new.png",
    ),
  );
  expect(unavailable).not.toHaveBeenCalled();
});

it("expires an already loaded image without waiting for a server cleanup", async () => {
  vi.useFakeTimers();
  try {
    const gone = vi.fn();
    render(
      <CaptureImage
        src="http://localhost/capture.png"
        alt="Capture"
        expiresAt={new Date(Date.now() + 1000).toISOString()}
        onUnavailable={gone}
      />,
    );
    fireEvent.load(screen.getByRole("img"));
    await act(async () => {
      vi.advanceTimersByTime(1001);
    });
    expect(screen.queryByRole("img")).not.toBeInTheDocument();
    expect(gone).toHaveBeenCalledOnce();
  } finally {
    vi.useRealTimers();
  }
});
