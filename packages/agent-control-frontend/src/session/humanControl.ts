import { create } from "zustand";
import { api, wsUrl } from "../api/client";

export type Lease = {
  id: string;
  session_id: string;
  generation: number;
  client_id: string;
  fence: number;
  surface: "browser" | "desktop";
  surface_id: string;
  viewport_revision: string;
  last_sequence: number;
};
type Entry = { lease?: Lease; error?: string; ready?: boolean };
export const useHumanControl = create<{ bots: Record<string, Entry> }>(() => ({
  bots: {},
}));
const clients = new Map<
  string,
  {
    socket: WebSocket;
    timer: ReturnType<typeof setInterval>;
    tail: Promise<void>;
    sequence: number;
    queued: number;
    pending?: { resolve: () => void; reject: (e: Error) => void };
  }
>();
function patch(id: string, value: Entry) {
  useHumanControl.setState((s) => ({ bots: { ...s.bots, [id]: value } }));
}
export function clientId() {
  return pageClientId;
}
const pageClientId = crypto.randomUUID();
export function leaseBody(lease: Lease) {
  return {
    request_id: crypto.randomUUID(),
    lease_id: lease.id,
    client_id: lease.client_id,
    fence: lease.fence,
  };
}
export async function takeControl(
  botId: string,
  sid: string,
  generation: number,
  surface: "browser" | "desktop",
) {
  const lease = await api<Lease>(
    `/api/bots/${botId}/sessions/${sid}/control/acquire`,
    {
      method: "POST",
      body: JSON.stringify({
        request_id: crypto.randomUUID(),
        client_id: clientId(),
        generation,
        surface,
      }),
    },
  );
  const query = new URLSearchParams({
    lease_id: lease.id,
    client_id: lease.client_id,
    fence: String(lease.fence),
  });
  const socket = new WebSocket(
    wsUrl(`/api/bots/${botId}/sessions/${sid}/control/ws?${query}`),
  );
  patch(botId, { lease, ready: false });
  const client = {
    socket,
    sequence: lease.last_sequence,
    queued: 0,
    tail: Promise.resolve(),
    pending: undefined as
      { resolve: () => void; reject: (e: Error) => void } | undefined,
    timer: setInterval(() => {
      void api(`/api/bots/${botId}/sessions/${sid}/control/renew`, {
        method: "POST",
        body: JSON.stringify(leaseBody(lease)),
      }).catch(() => socket.close());
    }, 10000),
  };
  clients.set(botId, client);
  socket.onopen = () => patch(botId, { lease, ready: true });
  socket.onmessage = (event) => {
    const result = JSON.parse(event.data);
    if (result.status === "rejected") {
      client.pending?.reject(new Error(result.detail));
      socket.close();
    } else client.pending?.resolve();
    client.pending = undefined;
  };
  socket.onclose = () => {
    clearInterval(client.timer);
    client.pending?.reject(
      new Error("Human control disconnected. Agent remains paused."),
    );
    clients.delete(botId);
    patch(botId, {
      error: "Control released. Resume the agent explicitly when ready.",
    });
  };
}
export async function releaseControl(botId: string) {
  const lease = useHumanControl.getState().bots[botId]?.lease;
  if (!lease) return;
  await api(`/api/bots/${botId}/sessions/${lease.session_id}/control/release`, {
    method: "POST",
    body: JSON.stringify(leaseBody(lease)),
  });
  clients.get(botId)?.socket.close();
}
export function humanInput(botId: string, input: Record<string, unknown>) {
  const client = clients.get(botId),
    lease = useHumanControl.getState().bots[botId]?.lease;
  if (!client || !lease) return;
  if (input.kind === "move" && client.queued >= 2) return;
  if (client.queued >= 32) {
    client.socket.close();
    return;
  }
  client.queued += 1;
  client.tail = client.tail
    .then(async () => {
      if (client.socket.readyState !== WebSocket.OPEN) return;
      const capture = input.kind === "release" ? { capture_id: "" } : await api<{ capture_id: string }>(
        `/api/bots/${botId}/captures/latest?surface=${lease.surface}`,
      );
      const sequence = ++client.sequence;
      await new Promise<void>((resolve, reject) => {
        const timeout = setTimeout(() => {
          client.socket.close();
          reject(new Error("Input acknowledgement timed out."));
        }, 10000);
        client.pending = {
          resolve: () => {
            clearTimeout(timeout);
            resolve();
          },
          reject: (e) => {
            clearTimeout(timeout);
            reject(e);
          },
        };
        client.socket.send(
          JSON.stringify({
            ...leaseBody(lease),
            generation: lease.generation,
            surface_id: lease.surface_id,
            viewport_revision: lease.viewport_revision,
            capture_id: capture.capture_id,
            sequence,
            input,
          }),
        );
      });
    })
    .finally(() => {
      client.queued -= 1;
    })
    .catch((error) => {
      patch(botId, { error: String(error) });
      client.socket.close();
    });
}
export function resetHumanControl() {
  for (const client of clients.values()) {
    clearInterval(client.timer);
    client.socket.close();
  }
  clients.clear();
  useHumanControl.setState({ bots: {} });
}
