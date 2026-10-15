import { api, ApiError, wsUrl } from "../api/client";
import type { ConnectionStatus } from "./reduce";
import { parseWireFrame } from "../api/wire";
import type { ServerEvent, Snapshot } from "./v2";

export class SessionConnection {
  private socket?: WebSocket;
  private stopped = false;
  private timer?: ReturnType<typeof setTimeout>;
  private attempts = 0;
  private captureRetention = false;
  private refreshing = false;
  private refreshRequested = false;
  private cursor?: number;
  private pending = new Map<string, string>();
  private abort = new AbortController();
  readonly protocol = 2;

  constructor(
    private botId: string,
    private onConnection: (status: ConnectionStatus) => void,
    private onSnapshot: (snapshot: Snapshot) => void,
    private onEvent: (event: ServerEvent) => void,
    private onError: (message: string) => void,
  ) {}

  start() {
    void this.discover();
  }
  private async discover() {
    this.onConnection("connecting");
    try {
      const capabilities = await api<{ protocol_version?: number; capture_retention?: boolean }>(
        "/api/capabilities",
        { signal: this.abort.signal },
      );
      if (this.stopped) return;
      if (capabilities.protocol_version === 2) {
        this.captureRetention = !!capabilities.capture_retention;
        this.connect();
      } else {
        this.onError("This client requires control protocol version 2. Update the server.");
        this.onConnection("disconnected");
      }
    } catch (error) {
      if (this.stopped) return;
      this.onError(error instanceof ApiError && (error.status === 404 || error.status === 501)
        ? "This client requires control protocol version 2. Update the server."
        : "Could not connect to the control server.");
      this.onConnection("disconnected");
    }
  }
  private connect() {
    const suffix = this.cursor === undefined ? "" : `?after_seq=${this.cursor}`;
    const socket = new WebSocket(
      wsUrl(`/api/bots/${this.botId}/events/ws${suffix}`),
    );
    this.socket = socket;
    socket.addEventListener("message", (event) => {
      if (this.stopped || this.socket !== socket) return;
      try {
        const frame = parseWireFrame(event.data);
        if ("data" in frame && frame.type === "snapshot" && "snapshot_seq" in frame.data) {
          if ((frame.data as Snapshot).bot_id !== this.botId) throw new Error("Unexpected bot snapshot");
          this.onSnapshot(frame.data as Snapshot);
          this.cursor = (frame.data as Snapshot).snapshot_seq;
        } else if (frame.type === "ready") {
          this.attempts = 0;
          this.onConnection("connected");
          if (this.captureRetention) void this.refreshCaptures();
        } else if ("schema_version" in frame && frame.schema_version === 2 && frame.bot_id === this.botId) {
          if (frame.seq <= (this.cursor ?? 0)) return;
          if (frame.seq !== (this.cursor ?? 0) + 1) {
            this.cursor = undefined;
            socket.close();
            return;
          }
          this.onEvent(frame);
          this.cursor = frame.seq;
          if (this.refreshing) this.refreshRequested = true;
          if (frame.type === "captures.changed") void this.refreshCaptures();
        } else {
          throw new Error("Unexpected event identity");
        }
      } catch {
        this.cursor = undefined;
        socket.close();
      }
    });
    socket.addEventListener("close", (event) => {
      if (this.stopped || this.socket !== socket) return;
      if (event.code === 1008 || event.code === 1000 || this.attempts >= 5) {
        this.onConnection("disconnected");
        return;
      }
      this.onConnection("reconnecting");
      this.timer = setTimeout(
        () => this.connect(),
        Math.min(500 * 2 ** this.attempts++, 8000),
      );
    });
  }

  async command(path: string, data: Record<string, unknown>): Promise<boolean> {
    const key = JSON.stringify({ path, data });
    const request_id = this.pending.get(key) ?? crypto.randomUUID();
    this.pending.set(key, request_id);
    try {
      const result = await api<{ accepted?: boolean; status?: string }>(path, {
        method: "POST",
        body: JSON.stringify({ ...data, request_id }),
        signal: this.abort.signal,
      });
      this.pending.delete(key);
      if (result.accepted === false)
        throw new Error(
          `Decision was not accepted. Current approval status: ${result.status ?? "unknown"}.`,
        );
      return !this.stopped;
    } catch (error) {
      if (!this.stopped) {
        this.onError(
          error instanceof Error
            ? error.message
            : "Command could not be confirmed.",
        );
        if (error instanceof ApiError && error.status < 500)
          this.pending.delete(key);
        // Keep ambiguous request IDs for an explicit retry; never queue execution on reconnect.
        try {
          await this.refresh();
        } catch {
          /* A later reconnect will reconcile. */
        }
      }
      return false;
    }
  }
  private async refreshCaptures() {
    this.refreshRequested = true;
    if (this.refreshing) return;
    this.refreshing = true;
    try {
      while (this.refreshRequested && !this.stopped) {
        this.refreshRequested = false;
        await this.refresh();
      }
    } catch { /* Retry with the next event or reconnect. */ }
    finally { this.refreshing = false; }
  }
  async refresh() {
    const snapshot = await api<Snapshot>(`/api/bots/${this.botId}/snapshot`, {
      signal: this.abort.signal,
    });
    if (!this.stopped && snapshot.snapshot_seq >= (this.cursor ?? 0)) {
      this.onSnapshot(snapshot);
      this.cursor = snapshot.snapshot_seq;
    }
  }
  stop() {
    this.stopped = true;
    this.abort.abort();
    clearTimeout(this.timer);
    this.socket?.close();
    this.pending.clear();
  }
}
