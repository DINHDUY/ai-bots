import { readFile } from "node:fs/promises";
import { expect, type Page, type WebSocketRoute } from "@playwright/test";

const stamp = "2026-10-07T09:40:00Z";
export const bots = [
  {
    id: "orders",
    name: "Orders ETL",
    framework: "microsoft",
    model: "gpt-4.1",
  },
  {
    id: "reporting",
    name: "Reporting Bot",
    framework: "anthropic",
    model: "claude-sonnet-5",
  },
  {
    id: "research",
    name: "Research Bot",
    framework: "microsoft",
    model: "gpt-4.1",
  },
  {
    id: "dev",
    name: "Dev Assistant",
    framework: "anthropic",
    model: "claude-sonnet-5",
  },
].map((bot) => ({
  ...bot,
  instructions:
    "Prepare and validate data, then request approval before publishing.",
  credential_id: "key",
  created_at: stamp,
  updated_at: stamp,
}));
export const summary = JSON.stringify(
  {
    source: "raw/orders/2026-10-06.csv",
    rows_in: 3,
    rows_out: 2,
    output: "curated/orders/2026-10-06.csv",
  },
  null,
  2,
);
export async function fixture(page: Page, initial = "/#/bots/orders") {
  const sockets: WebSocketRoute[] = [];
  const sent: { socket: number; frame: Record<string, unknown> }[] = [];
  const errors: string[] = [];
  const eventLists: Record<string, Record<string, unknown>[]> = Object.fromEntries(bots.map(bot => [bot.id, []]));
  const socketBots: string[] = [];
  const emit = (bid: string, type: string, data: Record<string, unknown>) => {
    const events = eventLists[bid];
    const event = { schema_version: 2, event_id: `${bid}_${events.length + 1}`, seq: events.length + 1,
      bot_id: bid, session_id: bid, run_id: `run_${bid}`, action_id: null, occurred_at: stamp, type, data };
    events.push(event);
    sockets.forEach((socket, index) => { if (socketBots[index] === bid) socket.send(JSON.stringify(event)); });
  };
  const snapshot = (bid: string) => ({ schema_version: 2, bot_id: bid, snapshot_seq: eventLists[bid].length,
    computer: { id: bid, status: "running" }, run: { id: `run_${bid}`, status: bid === "orders" ? "running" : "completed" },
    messages: [], messages_before: null, events: eventLists[bid], pending_approvals: [], observations_truncated: false });
  page.on("pageerror", (error) => errors.push(error.message));
  await page.clock.setFixedTime(new Date("2026-10-07T09:43:00Z"));
  await page.route("**/api/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    let body: unknown;
    if (path === "/api/capabilities") body = { protocol_version: 2 };
    else if (path.endsWith("/snapshot")) body = snapshot(path.split("/")[3]);
    else if (path.endsWith("/approval-policies")) body = [];
    else if (path.endsWith("/decision")) {
      const bid = path.split("/")[3];
      const data = route.request().postDataJSON();
      sent.push({ socket: socketBots.indexOf(bid), frame: { path, ...data } });
      emit(bid, "approval.resolved", { approval_id: path.split("/")[5], status: data.decision === "approve" ? "approved" : "denied", revision: 2 });
      body = { accepted: true };
    }
    else if (path === "/api/me") body = { id: "duy", username: "Duy" };
    else if (path === "/api/logout") body = { status: "ok" };
    else if (path === "/api/bots") body = bots;
    else if (path === "/api/workspace-deletions") body = { items: [], next_cursor: null };
    else if (path === "/api/credentials")
      body = [
        {
          id: "key",
          provider: "openai",
          label: "Project key",
          key_hint: "1234",
          endpoint: "",
          created_at: stamp,
          updated_at: stamp,
        },
      ];
    else if (path.startsWith("/api/bots/")) {
      const bot = bots.find((item) => item.id === path.split("/").at(-1));
      body = bot
        ? {
            ...bot,
            messages:
              bot.id === "orders"
                ? [
                    {
                      role: "user",
                      content:
                        "Clean yesterday’s Azure orders. Keep paid rows with valid amounts, then publish the CSV and summary to curated. Ask me before running the pipeline.",
                    },
                    {
                      role: "assistant",
                      content:
                        "I’ll inspect the source, prepare the transformation, and ask for approval before publishing. Follow the work in my cloud computer.",
                    },
                  ]
                : [],
          }
        : { detail: "Bot not found" };
    } else {
      await route.fulfill({
        status: 404,
        json: { detail: "Fixture route unavailable" },
      });
      return;
    }
    await route.fulfill({ json: body });
  });
  await page.routeWebSocket("**/events/ws**", (socket) => {
    const bid = new URL(socket.url()).pathname.split("/")[3];
    sockets.push(socket);
    socketBots.push(bid);
    socket.send(JSON.stringify({ type: "snapshot", data: snapshot(bid) }));
    socket.send(JSON.stringify({ type: "ready", seq: eventLists[bid].length }));
  });
  const preview = await readFile(
    new URL("./fixtures/orders-preview.html", import.meta.url),
    "utf8",
  );
  let screenshot = "";
  await expect(async () => {
    await imagePage.bringToFront();
    screenshot = (await imagePage.screenshot()).toString("base64");
  }).toPass({ timeout: 10_000 });
  await imagePage.close();
  await page.goto(initial);
  await expect.poll(() => sockets.length).toBe(4);
  await expect(
    page.getByRole("heading", {
      name: initial.includes("computer") ? "Live Cloud Computer" : "Orders ETL",
      exact: true,
    }),
  ).toBeVisible();
  const send = (frame: Record<string, unknown>, index = 0) => {
    const bid = socketBots[index];
    if (frame.event === "session") emit(bid, "session.bound", { status: "running" });
    else if (frame.event === "approval_required") emit(bid, "approval.required", { ...frame, revision: 1 });
    else if (frame.event === "done") emit(bid, "run.finished", { status: "completed", outcome: "completed" });
    else emit(bid, "observation", { frame });
  };
  send({ event: "session", session_id: "orders" });
  send({
    event: "log",
    type: "TOOL_CALL",
    payload: "browser_open: file:///workspace/preview.html",
  });
  send({ event: "log", type: "SCREENSHOT_CAPTURE", payload: screenshotBase64 });
  send({
    event: "log",
    type: "TOOL_CALL",
    payload:
      "bash: python3 -m py_compile /workspace/etl_orders.py\nScript validated.",
  });
  send({
    event: "artifact_written",
    meta: {
      path: "/workspace/etl_orders.py",
      preview:
        "from decimal import Decimal\n# Filter paid orders with valid decimal amounts.",
    },
  });
  send({
    event: "artifact_written",
    meta: {
      path: "/workspace/azure.env",
      preview: "RAW_READ_SAS=fixture-secret-never-show",
    },
  });
  send({
    event: "log",
    type: "RESULT",
    payload:
      "The preview contains **2 paid orders totaling $15.75**. One cancelled order is excluded. The script is ready.",
  });
  send({
    event: "approval_required",
    approval_id: "approve-etl",
    action: "bash",
    detail: "python3 /workspace/etl_orders.py",
  });
  send({ event: "session", session_id: "reporting" }, 1);
  await expect(
    page.getByRole("button", { name: "Notifications, 1 pending approvals" }),
  ).toBeVisible();
  async function completed() {
    send({
      event: "log",
      type: "TOOL_CALL",
      payload:
        "bash: python3 /workspace/etl_orders.py\nEXTRACT   raw/orders/2026-10-06.csv → 3 rows\nTRANSFORM paid orders → 2 rows\nLOAD      curated/orders/2026-10-06.csv · HTTP 201\nLOAD      curated/orders/2026-10-06.summary.json · HTTP 201",
    });
    send({
      event: "artifact_written",
      meta: {
        path: "/workspace/outputs/2026-10-06.csv",
        preview:
          "order_id,customer_id,amount,currency\n1001,c-9,12.50,USD\n1003,c-9,3.25,USD",
      },
    });
    send({
      event: "artifact_written",
      meta: {
        path: "/workspace/outputs/2026-10-06.summary.json",
        preview: summary,
      },
    });
    send({ event: "done", session_id: "orders" });
    await expect(
      page.getByRole("button", { name: "Notifications, 0 pending approvals" }),
    ).toBeVisible();
  }
  return { sockets, sent, errors, send, screenshot, completed };
}
