type Listener = (event: unknown) => void;

export class FakeWebSocket {
  static instances: FakeWebSocket[] = [];
  static CONNECTING = 0;
  static OPEN = 1;
  static CLOSING = 2;
  static CLOSED = 3;

  readyState: number = FakeWebSocket.CONNECTING;
  sent: string[] = [];
  seq = 0;
  get botId() { return new URL(this.url).pathname.split("/")[3]; }
  private listeners = new Map<string, Set<Listener>>();

  constructor(public url: string) {
    FakeWebSocket.instances.push(this);
    queueMicrotask(() => {
      if (this.readyState === FakeWebSocket.CLOSED) return;
      this.readyState = FakeWebSocket.OPEN;
      this.emit("open", {});
      if (String(this.url).includes("/events/ws")) {
        this.receive({ type: "snapshot", data: { schema_version: 2, bot_id: this.botId, snapshot_seq: 0,
          computer: null, run: null, messages: [], messages_before: null, events: [], pending_approvals: [], observations_truncated: false } });
        this.receive({ type: "ready", seq: 0 });
      }
    });
  }

  addEventListener(type: string, listener: Listener): void {
    const set = this.listeners.get(type) ?? new Set<Listener>();
    set.add(listener);
    this.listeners.set(type, set);
  }

  removeEventListener(type: string, listener: Listener): void {
    this.listeners.get(type)?.delete(listener);
  }

  send(data: string): void {
    this.sent.push(data);
  }

  close(): void {
    if (this.readyState === FakeWebSocket.CLOSED) return;
    this.readyState = FakeWebSocket.CLOSED;
    this.emit("close", {});
  }

  receive(frame: unknown): void {
    this.emit("message", { data: JSON.stringify(frame) });
  }

  publish(type: string, data: Record<string, unknown>): void {
    this.receive({ schema_version: 2, event_id: `${this.botId}_${++this.seq}`, seq: this.seq,
      bot_id: this.botId, session_id: this.botId, run_id: `run_${this.botId}`, action_id: null,
      occurred_at: "2026-01-01T00:00:00Z", type, data });
  }

  observation(frame: Record<string, unknown>): void {
    if (frame.event === "session") this.publish("session.bound", { status: "running" });
    else if (frame.event === "approval_required") this.publish("approval.required", { ...frame, revision: 1 });
    else this.publish("observation", { frame });
  }

  private emit(type: string, event: unknown): void {
    for (const listener of this.listeners.get(type) ?? []) listener(event);
  }
}
