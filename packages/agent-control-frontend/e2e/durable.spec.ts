import { test, expect, type Page, type WebSocketRoute } from "@playwright/test";

async function durableFixture(page: Page, manualOutcomes = false) {
  let acceptDecision: () => void = () => {};
  const decisionGate = new Promise<void>((resolve) => {
    acceptDecision = resolve;
  });
  const bot = {
    id: "durable",
    name: "Durable bot",
    framework: "microsoft",
    model: "gpt-4.1",
    instructions: "",
    credential_id: "key",
    created_at: "2026-10-07T12:00:00Z",
    updated_at: "2026-10-07T12:00:00Z",
  };
  const sockets = new Set<WebSocketRoute>();
  const subscriptions: string[] = [];
  const commands: { path: string; body: Record<string, unknown> }[] = [];
  const events: any[] = [];
  const messages: any[] = [];
  let run: { id: string; status: string } | null = null;
  let pending: any[] = [];
  const stamp = "2026-10-07T12:00:00Z";
  const snapshot = () => ({
    schema_version: 2,
    bot_id: bot.id,
    snapshot_seq: events.length,
    computer: run ? { id: "computer_durable", status: "running" } : null,
    run,
    messages,
    messages_before: null,
    events,
    pending_approvals: pending,
    observations_truncated: false,
  });
  const emit = (type: string, data: Record<string, unknown>) => {
    const event = {
      schema_version: 2,
      event_id: `event_${events.length + 1}`,
      seq: events.length + 1,
      bot_id: bot.id,
      session_id: "computer_durable",
      run_id: run?.id,
      action_id:
        type.startsWith("action.") || type.startsWith("approval.")
          ? "action_durable"
          : null,
      occurred_at: stamp,
      type,
      data,
    };
    events.push(event);
    if (type === "run.finished" && run) run.status = String(data.status);
    if (type === "message.created")
      messages.push({
        ...data,
        seq: event.seq,
        ordinal: messages.length + 1,
        occurred_at: stamp,
      });
    for (const socket of sockets) socket.send(JSON.stringify(event));
  };
  const install = async (target: Page) => {
    await target.route("**/api/**", async (route) => {
      const path = new URL(route.request().url()).pathname;
      if (route.request().method() === "POST") {
        const body = route.request().postDataJSON();
        commands.push({ path, body });
        if (path.endsWith("/runs")) {
          run = { id: "run_durable", status: "awaiting_approval" };
          pending = [
            {
              id: "approval_durable",
              action: "bash",
              detail: "python3 /workspace/report.py",
              revision: 1,
              created_at: stamp,
            },
          ];
          emit("message.created", {
            id: "message_user",
            role: "user",
            content: body.prompt,
          });
          emit("run.started", { status: "preparing" });
          emit("session.bound", { status: "running" });
          emit("approval.required", {
            approval_id: pending[0].id,
            action: pending[0].action,
            detail: pending[0].detail,
            revision: 1,
            ...(manualOutcomes
              ? {
                  policy_scope:
                    "Exact shell text; workspace revision abc. Any workspace change requires fresh approval.",
                  expires_at: "2026-10-07T12:02:00Z",
                }
              : {}),
          });
          await route.fulfill({
            status: 202,
            json: { run_id: run.id, status: run.status },
          });
          return;
        }
        if (path.endsWith("/decision")) {
          if (manualOutcomes) await decisionGate;
          pending = [];
          emit("approval.resolved", {
            approval_id: "approval_durable",
            status: "approved",
            revision: 2,
          });
          if (manualOutcomes) {
            run = { id: "run_durable", status: "running" };
            await route.fulfill({
              json: { accepted: true, status: "approved", revision: 2 },
            });
            return;
          }
          emit("message.created", {
            id: "message_result",
            role: "assistant",
            content: "The durable report is complete.",
          });
          run = { id: "run_durable", status: "completed" };
          emit("run.finished", { status: "completed" });
          await route.fulfill({ json: { status: "approved", revision: 2 } });
          return;
        }
      }
      let data: unknown;
      if (path === "/api/me") data = { id: "user", username: "Ada" };
      else if (path === "/api/capabilities") data = { protocol_version: 2 };
      else if (path === "/api/bots") data = [bot];
      else if (path.endsWith("/snapshot")) data = snapshot();
      else if (path === "/api/bots/durable")
        data = {
          ...bot,
          messages: messages.map(({ role, content }) => ({ role, content })),
        };
      else if (path === "/api/credentials") data = [];
      else {
        await route.fulfill({
          status: 404,
          json: { detail: "Missing fixture route" },
        });
        return;
      }
      await route.fulfill({ json: data });
    });
    await target.routeWebSocket("**/events/ws**", (socket) => {
      subscriptions.push(socket.url());
      sockets.add(socket);
      socket.onClose(() => {
        sockets.delete(socket);
      });
      const cursor = new URL(socket.url()).searchParams.get("after_seq");
      if (cursor === null)
        socket.send(JSON.stringify({ type: "snapshot", data: snapshot() }));
      socket.send(
        JSON.stringify({
          type: "ready",
          seq: cursor === null ? events.length : Number(cursor),
        }),
      );
      if (cursor !== null)
        for (const event of events.filter(
          (event) => event.seq > Number(cursor),
        ))
          socket.send(JSON.stringify(event));
    });
    await target.goto("/#/bots/durable");
    await expect(
      target.getByRole("heading", { name: bot.name, exact: true }),
    ).toBeVisible();
  };
  await install(page);
  return {
    install,
    commands,
    subscriptions,
    sockets,
    emit,
    events,
    acceptDecision,
  };
}

test("B2 shows submitting, accepted, executing, and failed command results", async ({
  page,
}) => {
  const fixture = await durableFixture(page, true);
  await page
    .getByRole("textbox", { name: "Message", exact: true })
    .fill("Prepare report");
  await page.getByRole("button", { name: "Send", exact: true }).click();
  const card = page.getByRole("article", { name: "Approval for bash" });
  await card.getByText("Save an approval rule").click();
  await expect(card.getByText(/workspace revision abc/)).toBeVisible();
  await card.getByRole("button", { name: "Allow once", exact: true }).click();
  await expect(
    card.getByText("Submitting decision…", { exact: true }),
  ).toBeVisible();
  await expect(
    card.getByRole("button", { name: "Allow once", exact: true }),
  ).toBeDisabled();
  fixture.acceptDecision();
  await expect(
    card.getByText("Decision accepted", { exact: true }),
  ).toBeVisible();
  fixture.emit("action.started", {
    operation: "bash",
    detail: "python3 /workspace/report.py",
    approval_id: "approval_durable",
  });
  await expect(
    card.getByText("Executing action", { exact: true }).first(),
  ).toBeVisible();
  fixture.emit("action.failed", {
    operation: "bash",
    approval_id: "approval_durable",
    command_id: "command_durable",
    ok: false,
    exit_code: 7,
    stdout: "",
    stderr: "Invalid input",
    stdout_truncated: false,
    timed_out: false,
    cancelled: false,
  });
  fixture.emit("run.finished", { status: "completed", failed_actions: 1 });
  await expect(card.getByText("Action result", { exact: true })).toBeVisible();
  await expect(card.getByText("Exit 7", { exact: true })).toBeVisible();
  await page.reload();
  await expect(card.getByText("Exit 7", { exact: true })).toBeVisible();
  expect(
    fixture.commands.filter((command) => command.path.endsWith("/decision")),
  ).toHaveLength(1);
});

test("v2 refresh and a second observer recover one run and approval", async ({
  page,
}) => {
  const fixture = await durableFixture(page);
  await page
    .getByRole("textbox", { name: "Message", exact: true })
    .fill("Prepare my report.");
  await expect(
    page.getByRole("button", { name: "Send", exact: true }),
  ).toBeEnabled();
  await page.getByRole("button", { name: "Send", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "Allow once", exact: true }),
  ).toBeVisible();
  await expect(page.getByText("Always allow", { exact: true })).toHaveCount(0);
  await page.reload();
  await expect(
    page.getByRole("button", { name: "Allow once", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByText("Prepare my report.", { exact: true }),
  ).toHaveCount(1);
  const second = await page.context().newPage();
  await fixture.install(second);
  await expect(
    second.getByRole("button", { name: "Allow once", exact: true }),
  ).toBeVisible();
  await second.getByRole("button", { name: "Allow once", exact: true }).click();
  for (const observer of [page, second]) {
    await expect(
      observer.getByText("Decision accepted", { exact: true }),
    ).toBeVisible();
    await expect(
      observer.getByText("The durable report is complete.", { exact: true }),
    ).toHaveCount(1);
  }
  expect(
    fixture.commands.filter((command) => command.path.endsWith("/runs")),
  ).toHaveLength(1);
  expect(
    fixture.commands.filter((command) => command.path.endsWith("/decision")),
  ).toHaveLength(1);
  expect(fixture.commands[1].body.revision).toBe(1);
  expect(typeof fixture.commands[0].body.request_id).toBe("string");
});

test("v2 reconnect resumes its sequence without replaying commands", async ({
  page,
}) => {
  const fixture = await durableFixture(page);
  await page
    .getByRole("textbox", { name: "Message", exact: true })
    .fill("Prepare my report.");
  await expect(
    page.getByRole("button", { name: "Send", exact: true }),
  ).toBeEnabled();
  await page.getByRole("button", { name: "Send", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "Allow once", exact: true }),
  ).toBeVisible();
  for (const socket of fixture.sockets)
    socket.close({ code: 1012, reason: "Reconnect fixture" });
  await expect.poll(() => fixture.subscriptions.length).toBe(2);
  expect(fixture.subscriptions[1]).toContain("after_seq=4");
  await expect(
    page.getByRole("button", { name: "Allow once", exact: true }),
  ).toBeEnabled();
  for (const socket of fixture.sockets)
    socket.send(JSON.stringify(fixture.events[0]));
  await expect(
    page.getByText("Prepare my report.", { exact: true }),
  ).toHaveCount(1);
  expect(fixture.commands).toHaveLength(1);
});
