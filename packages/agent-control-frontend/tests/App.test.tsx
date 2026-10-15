import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";
import { http, HttpResponse } from "msw";

import { App } from "../src/App";
import { FakeWebSocket } from "./support/fakeSocket";
import { server, state } from "./support/server";

async function signIn() {
  const user = userEvent.setup();
  render(<App />);
  const [username] = await screen.findAllByRole("textbox", {
    name: "Username",
  });
  const [password] = screen.getAllByLabelText("Password");
  await user.type(username!, "ada");
  await user.type(password!, "password1");
  await user.click(screen.getByRole("button", { name: "Sign in" }));
  await screen.findByText("ada");
  return user;
}

async function createBot(
  user: ReturnType<typeof userEvent.setup>,
  name: string,
) {
  await user.click(screen.getByRole("button", { name: "New bot" }));
  await screen.findByRole("option", { name: "Anthropic" });
  await user.type(screen.getByRole("textbox", { name: "Name" }), name);
  await user.click(screen.getByRole("button", { name: "Add bot" }));
  await screen.findByRole("heading", { name, level: 1 });
  await screen.findByRole("textbox", { name: "Message" });
}

describe("workspace", () => {
  beforeEach(() => {
    window.location.hash = "#/overview";
  });

  it("signs in, creates a bot, sends a prompt, and answers an approval", async () => {
    const user = await signIn();
    await createBot(user, "Writer");
    await waitFor(() => expect(FakeWebSocket.instances.length).toBe(1));

    await user.type(
      screen.getByRole("textbox", { name: "Message" }),
      "List files",
    );
    await user.click(screen.getByRole("button", { name: "Send" }));
    expect(screen.getByText("List files")).toBeInTheDocument();

    const socket = FakeWebSocket.instances[0]!;
    await waitFor(() => expect(state.commands[0]).toMatchObject({ prompt: "List files", request_id: expect.any(String) }));
    socket.observation({ event: "session", session_id: "b1" });
    socket.observation({
      event: "approval_required",
      approval_id: "ap1",
      action: "bash",
      detail: "ls",
    });
    expect(await screen.findByText("ls")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Allow once" }));
    await waitFor(() =>
      expect(state.commands.at(-1)).toMatchObject({ decision: "approve", revision: 1, request_id: expect.any(String) }),
    );
    expect(screen.getByText("Decision: Allowed")).toBeInTheDocument();
  });

  it("routes frames to the bot that owns the socket", async () => {
    const user = await signIn();
    await createBot(user, "Writer");
    await user.click(screen.getByRole("link", { name: "Overview" }));
    await createBot(user, "Editor");
    await user.click(screen.getByRole("link", { name: "Overview" }));
    await waitFor(() => expect(FakeWebSocket.instances.length).toBe(2));

    FakeWebSocket.instances[0]!.observation({
      event: "log",
      type: "RESULT",
      payload: "writer-result",
    });
    FakeWebSocket.instances[1]!.observation({
      event: "approval_required",
      approval_id: "ap2",
      action: "bash",
      detail: "editor-command",
    });

    expect(await screen.findByText("editor-command")).toBeInTheDocument();
    expect(screen.queryByText("writer-result")).not.toBeInTheDocument();

    await user.click(screen.getByRole("link", { name: "Writer · Idle" }));
    expect(await screen.findByText("writer-result")).toBeInTheDocument();
    expect(screen.queryByText("editor-command")).not.toBeInTheDocument();
  });

  it("adds a Foundry key and uses it when creating a microsoft bot", async () => {
    const user = await signIn();
    await user.click(screen.getByRole("link", { name: "API keys" }));
    await screen.findByRole("heading", { name: "API keys" });
    await user.selectOptions(
      screen.getByRole("combobox", { name: "Provider" }),
      "azure_foundry",
    );
    await user.type(screen.getByRole("textbox", { name: "Label" }), "Grok");
    await user.type(screen.getByLabelText("API key"), "secret-key-1");
    await user.type(
      screen.getByRole("textbox", { name: "Endpoint" }),
      "https://example.services.ai.azure.com/openai/v1",
    );
    await user.click(screen.getByRole("button", { name: "Add key" }));
    expect(await screen.findByText(/Grok/)).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "New bot" }));
    await user.selectOptions(
      screen.getByRole("combobox", { name: "Framework" }),
      "microsoft",
    );
    await screen.findByRole("option", { name: "Grok" });
    await user.type(screen.getByRole("textbox", { name: "Name" }), "Grok bot");
    expect(screen.getByRole("textbox", { name: "Model" })).toHaveValue(
      "grok-4",
    );
    await user.click(screen.getByRole("button", { name: "Add bot" }));
    await screen.findByRole("heading", { name: "Grok bot", level: 1 });
    await user.click(screen.getByRole("button", { name: "Bot settings" }));
    await screen.findByRole("heading", { name: "Bot settings" });
    expect(screen.getByRole("textbox", { name: "Model" })).toHaveValue(
      "grok-4",
    );
    expect(screen.getByRole("combobox", { name: "API key" })).toHaveValue("c2");
  });

  it("saves an optional default prompt and inserts it without sending", async () => {
    const instructions = "Summarize workspace documents and highlight unanswered questions.";
    const defaultPrompt = "Review the workspace files and summarize outstanding tasks.";
    const user = await signIn();
    await user.click(screen.getByRole("button", { name: "New bot" }));
    await screen.findByRole("option", { name: "Anthropic" });
    expect(screen.getByRole("textbox", { name: "Instructions" })).toHaveValue("");
    expect(screen.queryByRole("button", { name: "Azure Blob ETL" })).toBeNull();
    await user.type(screen.getByRole("textbox", { name: "Name" }), "Document assistant");
    await user.type(screen.getByRole("textbox", { name: "Instructions" }), instructions);
    await user.click(screen.getByRole("button", { name: "Add bot" }));
    await screen.findByRole("heading", { name: "Document assistant", level: 1 });
    await waitFor(() => expect(FakeWebSocket.instances.length).toBe(1));

    expect(screen.queryByRole("button", { name: "ETL prompt" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Default Prompt" })).toBeNull();
    await user.click(screen.getByRole("button", { name: "Bot settings" }));
    const prompt = screen.getByRole("textbox", { name: "Default Prompt (optional)" });
    await user.click(prompt);
    await user.paste(defaultPrompt);
    await user.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    await user.click(screen.getByRole("button", { name: "Default Prompt" }));
    const message = screen.getByRole("textbox", { name: "Message" });
    expect(message).toHaveValue(defaultPrompt);
    expect(state.commands).toHaveLength(0);

    await user.click(screen.getByRole("button", { name: "Bot settings" }));
    expect(screen.queryByRole("button", { name: "Apply ETL instructions" })).toBeNull();
    expect(screen.getByRole("textbox", { name: "Instructions" })).toHaveValue(
      instructions,
    );
    expect(screen.getByRole("textbox", { name: "Default Prompt (optional)" })).toHaveValue(defaultPrompt);
    await user.clear(screen.getByRole("textbox", { name: "Default Prompt (optional)" }));
    await user.type(screen.getByRole("textbox", { name: "Default Prompt (optional)" }), "   ");
    await user.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(screen.queryByRole("button", { name: "Default Prompt" })).toBeNull();
    expect(message).toHaveValue(defaultPrompt);
  });

  it("validates settings, shows saving and errors, then closes after a successful retry", async () => {
    server.use(http.get("*/api/capabilities", () => HttpResponse.json({ protocol_version: 2 })));
    const user = await signIn();
    await createBot(user, "Writer");
    let release!: () => void;
    const pending = new Promise<void>((resolve) => { release = resolve; });
    const requests: unknown[] = [];
    server.use(http.patch("*/api/bots/b1", async ({ request }) => {
      const body = await request.json();
      requests.push(body);
      if (requests.length === 1) {
        await pending;
        return HttpResponse.json({ detail: "Model is not available." }, { status: 400 });
      }
      Object.assign(state.bots[0]!, body);
      return HttpResponse.json(state.bots[0]);
    }));
    await user.click(screen.getByRole("button", { name: "Bot settings" }));
    const dialog = screen.getByRole("dialog", { name: "Bot settings" });
    const fields = within(dialog);
    await user.clear(fields.getByLabelText("Name"));
    await user.type(fields.getByLabelText("Name"), "Updated writer");
    await user.clear(fields.getByLabelText("Model"));
    await user.click(fields.getByRole("button", { name: "Save" }));
    expect(fields.getByRole("alert")).toHaveTextContent("Enter a model.");
    expect(requests).toHaveLength(0);
    await user.type(fields.getByLabelText("Model"), "new-model");
    await user.type(fields.getByLabelText("Instructions"), "Write concise answers.");
    await user.click(fields.getByRole("button", { name: "Save" }));
    try {
      expect(await fields.findByRole("button", { name: "Saving…" })).toBeDisabled();
      expect(fields.getByLabelText("Name")).toBeDisabled();
      expect(dialog).toBeVisible();
    } finally {
      release();
    }
    expect(await fields.findByRole("alert")).toHaveTextContent("Model is not available.");
    expect(fields.getByLabelText("Name")).toHaveValue("Updated writer");
    expect(fields.getByLabelText("Instructions")).toHaveValue("Write concise answers.");
    await user.click(fields.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "Bot settings" })).toBeNull());
    expect(requests).toHaveLength(2);
    expect(requests[1]).toEqual({
      name: "Updated writer", model: "new-model", credential_id: "cred-1",
      instructions: "Write concise answers.",
      default_prompt: "",
    });
    expect(await screen.findByRole("heading", { name: "Updated writer", level: 1 })).toBeVisible();
    await user.click(screen.getByRole("button", { name: "Bot settings" }));
    expect(screen.getByLabelText("Name")).toHaveValue("Updated writer");
    expect(screen.getByLabelText("Model")).toHaveValue("new-model");
    expect(screen.getByLabelText("Instructions")).toHaveValue("Write concise answers.");
  });

  it("creates a UFO bot from the Windows settings shortcut", async () => {
    state.credentials.push({ ...state.credentials[0]!, id: "openai-key", label: "OpenAI", provider: "openai" });
    server.use(
      http.get("*/api/capabilities", () => HttpResponse.json({ protocol_version: 2, windows_computers: true, frameworks: ["anthropic", "microsoft", "ufo"] })),
      http.get("*/api/computers", () => HttpResponse.json({ computers: [] })),
    );
    const user = await signIn();
    await createBot(user, "Writer");
    await user.click(screen.getByRole("button", { name: "Bot settings" }));
    await user.click(await screen.findByRole("link", { name: "Create Windows bot" }));
    expect(screen.queryByRole("dialog", { name: "Bot settings" })).toBeNull();
    const dialog = within(await screen.findByRole("dialog", { name: "New bot" }));
    expect(dialog.getByLabelText("Framework")).toHaveValue("ufo");
    await waitFor(() => expect(dialog.getByLabelText("API key")).toHaveValue("openai-key"));
    await user.type(dialog.getByLabelText("Name"), "Windows assistant");
    await user.click(dialog.getByRole("button", { name: "Add bot" }));
    await screen.findByRole("heading", { name: "Windows assistant", level: 1 });
    expect(state.bots.at(-1)).toMatchObject({ framework: "ufo", credential_id: "openai-key" });
  });
});
