import { useEffect, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useSearchParams } from "react-router-dom";
import { api, apiBase, type User } from "../../api/client";
import {
  channelState,
  type ChannelSnapshot,
  type ChannelMessage,
  type Peer,
} from "./channel";
import "./center.css";
import "./channel.css";

export function BotChannel() {
  const [params] = useSearchParams();
  const preferences = useQuery({
    queryKey: ["preferences"],
    queryFn: () => api<{ workspace_id: string | null }>("/api/preferences"),
  });
  const workspaces = useQuery({
    queryKey: ["workspaces"],
    queryFn: () => api<{ id: string; name: string; role: string }[]>("/api/workspaces"),
    refetchInterval: 5000,
  });
  const [selected, setSelected] = useState("");
  const requested = selected || params.get("workspace") || preferences.data?.workspace_id;
  const personal = workspaces.data?.find(w => w.role === "owner" && w.id.startsWith("personal_"));
  const wid = workspaces.data?.some(w => w.id === requested) ? requested! : personal?.id || workspaces.data?.[0]?.id || "";
  return (
    <section className="workspace-center">
      <div className="center-heading">
        <div>
          <h1>Bot channel</h1>
          <p className="muted">Your bots, working together.</p>
        </div>
        <Link to="/workspace?tab=collaboration">Collaboration settings</Link>
      </div>
      <label className="channel-workspace">
        Workspace
        <select value={wid} onChange={(e) => setSelected(e.target.value)}>
          {workspaces.data?.map((w) => (
            <option key={w.id} value={w.id}>
              {w.name}
            </option>
          ))}
        </select>
      </label>
      {wid ? (
        <ChannelPanel
          key={wid}
          wid={wid}
          initialThread={wid === requested ? params.get("thread") || "" : ""}
        />
      ) : (
        <p role="status">Loading workspace…</p>
      )}
    </section>
  );
}

export function CollaborationSettings({ wid }: { wid: string }) {
  const query = useQuery({
    queryKey: ["channel", wid],
    queryFn: () => api<ChannelSnapshot>(`/api/workspaces/${wid}/channel`),
    refetchOnWindowFocus: true,
  });
  const client = useQueryClient();
  const [draft, setDraft] = useState<{
    revision: number;
    enabled: boolean;
    enroll_future: boolean;
    enroll_bot_ids: string[];
  } | null>(null);
  const [error, setError] = useState("");
  const [saved, setSaved] = useState(false);
  const [busy, setBusy] = useState(false);
  if (!query.data)
    return (
      <p role={query.isError ? "alert" : "status"}>
        {query.isError ? String(query.error) : "Loading collaboration…"}
      </p>
    );
  const data = query.data;
  const value = draft ?? {
    revision: data.revision,
    enabled: !!data.enabled,
    enroll_future: data.enroll_future,
    enroll_bot_ids: [],
  };
  const editable = data.role === "owner";
  return (
    <section
      className="center-card channel-settings"
      aria-label="Workspace collaboration"
    >
      <h2>Automatic collaboration</h2>
      <p>
        Bots can discover published peers and request help. Each bot keeps its
        own tools, approvals, and computer.
      </p>
      <label className="channel-check">
        <input
          type="checkbox"
          checked={value.enabled}
          disabled={!editable || busy}
          onChange={(e) => {
            setDraft({ ...value, enabled: e.target.checked });
            setSaved(false);
          }}
        />
        Enable automatic collaboration
      </label>
      <fieldset disabled={!editable || busy}>
        <legend>Enroll your bots</legend>
        <p className="muted">
          Publishes their name and purpose to workspace members and adds the Bot
          channel tool. Other owners enroll their own bots.
        </p>
        {data.owned_bots.map((bot) => (
          <label className="channel-check" key={bot.bot_id}>
            <input
              type="checkbox"
              checked={
                bot.state === "enabled" ||
                value.enroll_bot_ids.includes(bot.bot_id)
              }
              disabled={bot.state === "enabled"}
              onChange={(e) =>
                setDraft({
                  ...value,
                  enroll_bot_ids: e.target.checked
                    ? [...value.enroll_bot_ids, bot.bot_id]
                    : value.enroll_bot_ids.filter((id) => id !== bot.bot_id),
                })
              }
            />
            {bot.name}
            <small>{channelState(bot.state)}</small>
          </label>
        ))}
        {!data.owned_bots.length ? (
          <p>No bots owned by you in this workspace.</p>
        ) : null}
      </fieldset>
      <label className="channel-check">
        <input
          type="checkbox"
          checked={value.enroll_future}
          disabled={!editable || busy}
          onChange={(e) =>
            setDraft({ ...value, enroll_future: e.target.checked })
          }
        />
        Select collaboration for my new bots
      </label>
      <p className="muted">
        You can opt out when creating a bot. Disable individual participation in
        Bot settings.
      </p>
      {error ? <p role="alert">{error}</p> : null}
      {saved ? <p role="status">Collaboration saved.</p> : null}
      <div className="row">
        <button
          type="button"
          disabled={!editable || busy}
          onClick={async () => {
            setBusy(true);
            setError("");
            setSaved(false);
            try {
              const result = await api<ChannelSnapshot>(
                `/api/workspaces/${wid}/channel`,
                { method: "PATCH", body: JSON.stringify(value) },
              );
              client.setQueryData(["channel", wid], result);
              setDraft(null);
              setSaved(true);
              await client.invalidateQueries({ queryKey: ["bot-tools"] });
              await client.invalidateQueries({ queryKey: ["bots"] });
            } catch (e) {
              setError(String(e));
            } finally {
              setBusy(false);
            }
          }}
        >
          {busy ? "Saving…" : "Save collaboration"}
        </button>
        <button
          type="button"
          disabled={busy}
          onClick={async () => {
            await query.refetch();
            setDraft(null);
            setError("");
          }}
        >
          Reload saved settings
        </button>
        <Link to={`/channel?workspace=${encodeURIComponent(wid)}`}>
          Open channel
        </Link>
      </div>
    </section>
  );
}

export function ChannelPanel({
  wid,
  initialThread = "",
}: {
  wid: string;
  initialThread?: string;
}) {
  const client = useQueryClient();
  const query = useQuery({
    queryKey: ["channel", wid],
    queryFn: () =>
      api<ChannelSnapshot>(`/api/workspaces/${wid}/channel/snapshot`),
    refetchInterval: 10000,
  });
  const me = useQuery({
    queryKey: ["me"],
    queryFn: () => api<User>("/api/me"),
  });
  const [thread, setThread] = useState(initialThread);
  const [recipient, setRecipient] = useState("");
  const [text, setText] = useState("");
  const [computer, setComputer] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [older, setOlder] = useState<ChannelMessage[]>([]);
  const [cursor, setCursor] = useState<number | null | undefined>(undefined);
  const [morePeers, setMorePeers] = useState<Peer[]>([]);
  const [peerCursor, setPeerCursor] = useState<number | null | undefined>(
    undefined,
  );
  const [systemEvents, setSystemEvents] = useState<
    { seq: number; kind: string; data: { name?: string; state?: string } }[]
  >([]);
  const requestRef = useRef<{ digest: string; id: string } | null>(null);
  const messages = useQuery({
    queryKey: ["channel-thread", wid, thread, query.data?.seq],
    queryFn: () =>
      api<{ messages: ChannelMessage[]; next_before: number | null }>(
        `/api/workspaces/${wid}/channel/messages?thread_id=${encodeURIComponent(thread)}`,
      ),
    enabled: !!thread,
  });
  const initialized = !!query.data;
  useEffect(() => {
    if (!initialized) return;
    let disposed = false,
      socket: WebSocket | undefined,
      timer: ReturnType<typeof setTimeout> | undefined;
    let after =
      client.getQueryData<ChannelSnapshot>(["channel", wid])?.seq ?? 0;
    function connect() {
      const url = new URL(
        `${apiBase()}/api/workspaces/${wid}/channel/events/ws`,
        location.href,
      );
      url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
      url.searchParams.set("after_seq", String(after));
      socket = new WebSocket(url);
      socket.addEventListener("message", (event) => {
        const page = JSON.parse(event.data);
        if (page.resync_required) {
          after = 0;
          void query.refetch().then((r) => {
            after = r.data?.seq ?? 0;
          });
        } else after = page.next_seq;
        if (page.events?.length || page.resync_required) {
          void client.invalidateQueries({ queryKey: ["channel", wid] });
          setSystemEvents((previous) =>
            [
              ...new Map(
                [
                  ...previous,
                  ...page.events.filter((e: { kind: string }) =>
                    e.kind.startsWith("bot."),
                  ),
                ].map((e) => [e.seq, e]),
              ).values(),
            ].slice(-30),
          );
        }
      });
      socket.addEventListener("close", (event) => {
        if (disposed) return;
        if (event.code === 1008) {
          void client.resetQueries({ queryKey: ["channel", wid] });
          return;
        }
        timer = setTimeout(connect, 2000);
      });
    }
    connect();
    return () => {
      disposed = true;
      clearTimeout(timer);
      socket?.close();
    };
    // The stream owns its cursor; snapshot updates must not reconnect it.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [wid, initialized, client]);
  useEffect(() => {
    setMorePeers([]);
    setPeerCursor(undefined);
  }, [query.data?.directory.revision]);
  if (query.isError || !query.data)
    return (
      <p role={query.isError ? "alert" : "status"}>
        {query.isError ? String(query.error) : "Loading bot channel…"}
        <button type="button" onClick={() => void query.refetch()}>
          Reload channel
        </button>
      </p>
    );
  const data = query.data;
  const peers = [...data.directory.bots, ...morePeers];
  const names = new Map(peers.map((b) => [b.bot_id, b.name]));
  const selectedThread = data.threads.find((t) => t.id === thread);
  const page = thread ? messages.data : data;
  const feed = [
    ...new Map(
      [...older, ...(page?.messages ?? [])].map((m) => [m.id, m]),
    ).values(),
  ].sort((a, b) => a.seq - b.seq);
  const next = cursor === undefined ? page?.next_before : cursor;
  return (
    <div className="channel-layout">
      <aside
        className="center-card channel-directory"
        aria-label="Bot directory"
      >
        <h2>Workspace bots</h2>
        {!data.enabled ? (
          <p>Collaboration is off. Enable it in Workspace settings.</p>
        ) : null}
        {peers.map((bot) => (
          <article key={bot.bot_id}>
            <strong>{bot.name}</strong>
            <span>{channelState(bot.availability)}</span>
            <p>{bot.purpose || "No public purpose set"}</p>
            <small>{bot.capabilities.join(" · ")}</small>
          </article>
        ))}
        {!peers.length ? (
          <p>No published bots yet. Enroll bots in Collaboration settings.</p>
        ) : null}
        {(peerCursor === undefined ? data.directory.next_offset : peerCursor) !=
        null ? (
          <button
            type="button"
            onClick={async () => {
              try {
                const page = await api<ChannelSnapshot["directory"]>(
                  `/api/workspaces/${wid}/bots/directory?offset=${peerCursor ?? data.directory.next_offset}`,
                );
                setMorePeers((p) => [...p, ...page.bots]);
                setPeerCursor(page.next_offset);
              } catch (e) {
                setError(String(e));
              }
            }}
          >
            More bots
          </button>
        ) : null}
      </aside>
      <section
        className="channel-conversation"
        aria-label="Channel conversation"
      >
        <div className="channel-toolbar">
          <label>
            Conversation
            <select
              value={thread}
              onChange={(e) => {
                setThread(e.target.value);
                setOlder([]);
                setCursor(undefined);
              }}
            >
              <option value="">All threads</option>
              {data.threads.map((t) => (
                <option key={t.id} value={t.id}>
                  {channelState(t.state)} · {t.id.slice(-8)}
                </option>
              ))}
            </select>
          </label>
          {selectedThread ? (
            <>
              <span>
                {channelState(selectedThread.state)} ·{" "}
                {selectedThread.runs_used}/{selectedThread.run_limit ?? 8} runs
              </span>
              {["open", "waiting_peer"].includes(selectedThread.state) &&
              (data.role === "owner" ||
                selectedThread.principal_id === me.data?.id) ? (
                <button
                  type="button"
                  disabled={busy}
                  onClick={async () => {
                    try {
                      await api(
                        `/api/workspaces/${wid}/channel/threads/${thread}/cancel`,
                        { method: "POST" },
                      );
                      await query.refetch();
                    } catch (e) {
                      setError(String(e));
                    }
                  }}
                >
                  Stop thread
                </button>
              ) : null}
            </>
          ) : null}
        </div>
        {next ? (
          <button
            type="button"
            onClick={async () => {
              try {
                const result = await api<{
                  messages: ChannelMessage[];
                  next_before: number | null;
                }>(
                  `/api/workspaces/${wid}/channel/messages?before=${next}${thread ? `&thread_id=${encodeURIComponent(thread)}` : ""}`,
                );
                setOlder((p) => [...result.messages, ...p]);
                setCursor(result.next_before);
              } catch (e) {
                setError(String(e));
              }
            }}
          >
            Earlier messages
          </button>
        ) : null}
        <div className="channel-feed">
          {feed.map((message) => (
            <article
              className="channel-message"
              key={message.id}
              id={message.id}
            >
              <header>
                <strong>
                  {message.sender_name}
                  {message.recipient_id
                    ? ` → ${names.get(message.recipient_id) || "Removed bot"}`
                    : ""}
                </strong>
                <time dateTime={message.created_at}>
                  {new Date(message.created_at).toLocaleTimeString([], {
                    hour: "2-digit",
                    minute: "2-digit",
                  })}
                </time>
              </header>
              {message.reply_to ? (
                <small>Reply to request {message.reply_to.slice(-8)}</small>
              ) : null}
              <p>{message.body}</p>
              {message.artifacts?.map((artifact, index) =>
                artifact.revoked ? (
                  <small key={artifact.id}>Shared file revoked</small>
                ) : (
                  <a
                    key={artifact.id}
                    href={`${apiBase()}/api/workspaces/${wid}/channel/artifacts/${artifact.id}`}
                    download
                  >
                    Download shared file {index + 1}
                  </a>
                ),
              )}
              <footer>
                <button
                  type="button"
                  onClick={() => {
                    setThread(message.thread_id);
                    setOlder([]);
                    setCursor(undefined);
                  }}
                >
                  View thread
                </button>
                <small>Posted</small>
                {data.deliveries
                  .filter((d) => d.message_id === message.id)
                  .map((d) => (
                    <span key={d.id} title={d.reason ?? undefined}>
                      {channelState(d.state)}
                      {d.reason ? ` · ${channelState(d.reason)}` : ""}
                      {d.run_id ? (
                        <>
                          {" "}
                          ·{" "}
                          <Link to={`/bots/${d.target_bot_id}`}>
                            View bot run
                          </Link>
                        </>
                      ) : null}
                    </span>
                  ))}
              </footer>
            </article>
          ))}
          {!feed.length ? (
            <p className="muted">
              No messages yet. Send a task to an enrolled bot.
            </p>
          ) : null}
        </div>
        {systemEvents.length ? (
          <details className="channel-events">
            <summary>Membership updates ({systemEvents.length})</summary>
            {systemEvents.map((e) => (
              <p key={e.seq}>
                {e.data.name || "Bot"} ·{" "}
                {channelState(e.data.state || e.kind.slice(4))}
              </p>
            ))}
          </details>
        ) : null}
        {error ? <p role="alert">{error}</p> : null}
        {messages.isError ? (
          <p role="alert">Could not load this thread.</p>
        ) : null}
        {data.role !== "viewer" ? (
          <form
            className="channel-compose"
            onSubmit={async (e) => {
              e.preventDefault();
              if (busy) return;
              setBusy(true);
              setError("");
              const payload = {
                kind: "request",
                recipient_id: recipient,
                text: text.trim(),
                requires_computer: computer,
              };
              const digest = JSON.stringify(payload);
              if (requestRef.current?.digest !== digest)
                requestRef.current = { digest, id: crypto.randomUUID() };
              try {
                const result = await api<ChannelMessage>(
                  `/api/workspaces/${wid}/channel/messages`,
                  {
                    method: "POST",
                    body: JSON.stringify({
                      request_id: requestRef.current.id,
                      ...payload,
                    }),
                  },
                );
                requestRef.current = null;
                setText("");
                setThread(result.thread_id);
                setOlder([]);
                setCursor(undefined);
                await query.refetch();
              } catch (e) {
                setError(String(e));
              } finally {
                setBusy(false);
              }
            }}
          >
            <label>
              Recipient
              <select
                required
                value={recipient}
                onChange={(e) => setRecipient(e.target.value)}
                disabled={busy || !data.enabled}
              >
                <option value="">Choose a bot</option>
                {peers
                  .filter((b) => b.state === "enabled")
                  .map((b) => (
                    <option key={b.bot_id} value={b.bot_id}>
                      {b.name} · {b.bot_id.slice(-6)}
                    </option>
                  ))}
              </select>
            </label>
            <label>
              Task
              <textarea
                required
                maxLength={8192}
                rows={3}
                value={text}
                onChange={(e) => setText(e.target.value)}
                disabled={busy || !data.enabled}
                placeholder="Ask a question or describe the task…"
              />
            </label>
            <div className="channel-toolbar">
              <label className="channel-check">
                <input
                  type="checkbox"
                  checked={computer}
                  onChange={(e) => setComputer(e.target.checked)}
                />
                Requires computer tools
              </label>
              <button
                disabled={busy || !data.enabled || !recipient || !text.trim()}
              >
                {busy ? "Sending…" : "Send task"}
              </button>
            </div>
            <small>
              Computer tasks wait for a ready computer and available control.
            </small>
          </form>
        ) : null}
      </section>
    </div>
  );
}
