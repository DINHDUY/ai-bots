import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";
import { FakeWebSocket } from "./fakeSocket";

import type { BotDetail, Credential, User } from "../../src/api/client";

const base = "http://127.0.0.1:8000";

const seededKey = (): Credential => ({
  id: "cred-1",
  provider: "anthropic",
  label: "Anthropic",
  endpoint: "",
  key_hint: "1234",
  created_at: "2026-01-01T00:00:00+00:00",
  updated_at: "2026-01-01T00:00:00+00:00",
});

export const state: { user: User | null; bots: BotDetail[]; credentials: Credential[]; commands: Record<string, unknown>[] } = {
  user: null,
  bots: [],
  credentials: [seededKey()],
  commands: [],
};

export function resetState(): void {
  state.user = null;
  state.commands = [];
  state.bots = [];
  state.credentials = [seededKey()];
}

function stamp(): string {
  return "2026-01-01T00:00:00+00:00";
}

export const server = setupServer(
  http.get(`${base}/api/capabilities`, () => HttpResponse.json({ protocol_version: 2 })),
  http.get(`${base}/api/preferences`, () => HttpResponse.json({})),
  http.get(`${base}/api/bots/:id/computer`, () => HttpResponse.json({ compatible: false, capabilities: {} })),
  http.get(`${base}/api/bots/:id/approval-policies`, () => HttpResponse.json([])),
  http.post(`${base}/api/bots/:id/runs`, async ({ request, params }) => {
    const body = await request.json() as Record<string, unknown>;
    state.commands.push(body);
    const socket = FakeWebSocket.instances.find(s => s.botId === params.id)!;
    socket.publish("message.created", { id: "message_1", role: "user", content: body.prompt });
    socket.publish("run.admitted", { status: "running" });
    return HttpResponse.json({ run_id: `run_${params.id}`, status: "running" });
  }),
  http.post(`${base}/api/bots/:id/approvals/:aid/decision`, async ({ request, params }) => {
    const body = await request.json() as Record<string, unknown>;
    state.commands.push(body);
    const socket = FakeWebSocket.instances.find(s => s.botId === params.id)!;
    socket.publish("approval.resolved", { approval_id: params.aid, status: body.decision === "approve" ? "approved" : "denied", revision: 2 });
    return HttpResponse.json({ accepted: true });
  }),
  http.get(`${base}/api/me`, () => {
    if (!state.user) return HttpResponse.json({ detail: "Sign in required." }, { status: 401 });
    return HttpResponse.json(state.user);
  }),
  http.post(`${base}/api/login`, async ({ request }) => {
    const body = (await request.json()) as { username?: string; password?: string };
    if (!body.username || !body.password || body.password.length < 8) {
      return HttpResponse.json({ detail: "Invalid username or password." }, { status: 401 });
    }
    state.user = { id: "user-1", username: body.username };
    return HttpResponse.json(state.user);
  }),
  http.post(`${base}/api/register`, async ({ request }) => {
    const body = (await request.json()) as { username?: string };
    state.user = { id: "user-1", username: body.username ?? "ada" };
    return HttpResponse.json(state.user);
  }),
  http.post(`${base}/api/logout`, () => {
    state.user = null;
    return HttpResponse.json({ status: "ok" });
  }),
  http.get(`${base}/api/bots`, () => {
    return HttpResponse.json(
      state.bots.map((bot) => ({
        id: bot.id,
        name: bot.name,
        framework: bot.framework,
        instructions: bot.instructions,
        default_prompt: bot.default_prompt ?? "",
        credential_id: bot.credential_id,
        model: bot.model,
        created_at: bot.created_at,
        updated_at: bot.updated_at,
      })),
    );
  }),
  http.post(`${base}/api/bots`, async ({ request }) => {
    const body = (await request.json()) as {
      name: string;
      framework: string;
      instructions?: string;
      default_prompt?: string;
      credential_id?: string;
      model?: string;
    };
    const bot: BotDetail = {
      id: `b${state.bots.length + 1}`,
      name: body.name,
      framework: body.framework,
      instructions: body.instructions ?? "",
      default_prompt: body.default_prompt ?? "",
      credential_id: body.credential_id ?? null,
      model: body.model ?? "",
      created_at: stamp(),
      updated_at: stamp(),
      messages: [],
    };
    state.bots.push(bot);
    return HttpResponse.json(bot, { status: 201 });
  }),
  http.get(`${base}/api/credentials`, () => HttpResponse.json(state.credentials)),
  http.post(`${base}/api/credentials`, async ({ request }) => {
    const body = (await request.json()) as { provider: string; label: string; api_key: string; endpoint?: string };
    const item: Credential = {
      id: `c${state.credentials.length + 1}`,
      provider: body.provider,
      label: body.label,
      endpoint: body.endpoint ?? "",
      key_hint: body.api_key.slice(-4),
      created_at: stamp(),
      updated_at: stamp(),
    };
    state.credentials.push(item);
    return HttpResponse.json(item, { status: 201 });
  }),
  http.delete(`${base}/api/credentials/:id`, ({ params }) => {
    const next = state.credentials.filter((item) => item.id !== params.id);
    if (next.length === state.credentials.length) {
      return HttpResponse.json({ detail: "API key not found." }, { status: 404 });
    }
    state.credentials = next;
    return HttpResponse.json({ status: "deleted", id: params.id });
  }),
  http.patch(`${base}/api/bots/:id`, async ({ request, params }) => {
    const bot = state.bots.find((item) => item.id === params.id);
    if (!bot) return HttpResponse.json({ detail: "Bot not found." }, { status: 404 });
    const body = (await request.json()) as Partial<BotDetail>;
    if (typeof body.name === "string") bot.name = body.name;
    if (typeof body.instructions === "string") bot.instructions = body.instructions;
    if (typeof body.default_prompt === "string") bot.default_prompt = body.default_prompt.trim();
    if (typeof body.credential_id === "string") bot.credential_id = body.credential_id;
    if (typeof body.model === "string") bot.model = body.model;
    bot.updated_at = stamp();
    return HttpResponse.json(bot);
  }),
  http.get(`${base}/api/bots/:id`, ({ params }) => {
    const bot = state.bots.find((item) => item.id === params.id);
    if (!bot) return HttpResponse.json({ detail: "Bot not found." }, { status: 404 });
    return HttpResponse.json(bot);
  }),
);
