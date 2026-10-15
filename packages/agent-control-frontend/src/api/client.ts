export type User = { id: string; username: string };

export type ToolSelection = { library_id: string; tool_id: string; version: string; configuration: { resource_id?: string } };
export type ToolSpec = ToolSelection & { library_name: string; name: string; description: string; compatible: boolean; reason: string; resource: "connector" | "skill" | null; bundle: boolean };
export type ToolState = { tools_revision: number; tool_selection: ToolSelection[]; editable: boolean; bindings: (ToolSelection & { ready: boolean; reason: string })[]; resources: Record<"connector" | "skill", { id: string; name: string }[]> };

export type Bot = {
  tools_revision?: number;
  tool_selection?: ToolSelection[];
  selected_count?: number;
  ready_count?: number;
  id: string;
  name: string;
  framework: string;
  instructions: string;
  default_prompt?: string;
  credential_id: string | null;
  model: string;
  created_at: string;
  updated_at: string;
};

export type Credential = {
  id: string;
  provider: string;
  label: string;
  endpoint: string;
  key_hint: string;
  created_at: string;
  updated_at: string;
};

export function providersFor(framework: string): string[] | null {
  if (framework === "anthropic") return ["anthropic"];
  if (framework === "microsoft" || framework === "ufo") return ["openai", "azure_foundry"];
  return null;
}

export function suggestedModel(provider: string): string {
  if (provider === "openai") return "gpt-4.1";
  if (provider === "azure_foundry") return "grok-4";
  return "claude-sonnet-5";
}

export type TranscriptMessage = { role: "user" | "assistant"; content: string };

export type BotDetail = Bot & { messages: TranscriptMessage[] };

export function apiBase(): string {
  const configured = import.meta.env.VITE_API_BASE || "http://127.0.0.1:8000";
  return configured.replace(/\/$/, "");
}

export function wsUrl(path: string): string {
  return `${apiBase().replace(/^http/, "ws")}${path}`;
}

export class ApiError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

export async function api<T>(path: string, options: RequestInit = {}): Promise<T> {
  const headers = new Headers(options.headers);
  if (options.body && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  const response = await fetch(`${apiBase()}${path}`, {
    ...options,
    credentials: "include",
    headers,
  });
  const text = await response.text();
  let body: { detail?: unknown } | null = null;
  if (text) {
    try { body = JSON.parse(text) as { detail?: unknown }; }
    catch (cause) {
      // Servers and proxies can return plain text or HTML for failed requests.
      if (response.ok) throw new Error("The server returned an invalid response.", { cause });
    }
  }
  if (!response.ok) {
    const detail = body && typeof body.detail === "string" ? body.detail : body?.detail && typeof body.detail === "object" && "message" in body.detail ? String(body.detail.message) : response.statusText;
    throw new ApiError(response.status, detail);
  }
  return body as T;
}
