import { useEffect, useRef, useState } from "react";
import { Terminal } from "@xterm/xterm";
import { FitAddon } from "@xterm/addon-fit";
import "@xterm/xterm/css/xterm.css";
import { api, wsUrl } from "../../api/client";
import { leaseBody, useHumanControl } from "../../session/humanControl";
import styles from "./workspace.module.css";

export function InteractiveTerminal({ botId }: { botId: string }) {
  const lease = useHumanControl((s) => s.bots[botId]?.lease);
  const [terminalId, setTerminalId] = useState<string>();
  const [error, setError] = useState("");
  const host = useRef<HTMLDivElement>(null);
  const socketRef = useRef<WebSocket | null>(null);
  useEffect(() => {
    setTerminalId(undefined);
  }, [lease?.id]);
  useEffect(() => {
    if (!terminalId || !lease || !host.current) return;
    const term = new Terminal({
      cursorBlink: true,
      scrollback: 2000,
      fontSize: 13,
      theme: { background: "#101316", foreground: "#e6e8eb" },
    });
    // Consume OSC 52 without granting clipboard access.
    term.parser.registerOscHandler(52, () => true);
    const fit = new FitAddon();
    term.loadAddon(fit);
    term.open(host.current);
    fit.fit();
    const params = new URLSearchParams({
      client_id: lease.client_id,
      fence: String(lease.fence),
      offset: "0",
    });
    const socket = new WebSocket(
      wsUrl(
        `/api/bots/${botId}/sessions/${lease.session_id}/terminals/${terminalId}/ws?${params}`,
      ),
    );
    socketRef.current = socket;
    const send = (value: object) => {
      if (socket.readyState === WebSocket.OPEN)
        socket.send(JSON.stringify(value));
    };
    socket.onopen = () => {
      send({ op: "resize", cols: term.cols, rows: term.rows });
      term.focus();
    };
    socket.onmessage = (e) => {
      const result = JSON.parse(e.data);
      if (result.type === "output") {
        if (result.gap)
          term.writeln(
            "\r\n[Earlier terminal output is no longer retained]\r\n",
          );
        const bytes = Uint8Array.from(atob(result.data), (c) =>
          c.charCodeAt(0),
        );
        term.write(bytes);
        if (result.exited) term.writeln("\r\n[Shell exited]");
      }
    };
    socket.onclose = () => {
      term.writeln("\r\n[Terminal closed. Agent remains paused.]");
      setError("Terminal closed. Reopen it under the current control lease.");
    };
    const input = term.onData((data) => {
      const bytes = new TextEncoder().encode(data);
      for (let offset = 0; offset < bytes.length; offset += 4096)
        send({
          op: "write",
          data: btoa(
            String.fromCharCode(...bytes.slice(offset, offset + 4096)),
          ),
        });
    });
    const observer = new ResizeObserver(() => {
      fit.fit();
      send({ op: "resize", cols: term.cols, rows: term.rows });
    });
    observer.observe(host.current);
    return () => {
      socket.close();
      input.dispose();
      observer.disconnect();
      term.dispose();
    };
  }, [botId, terminalId, lease?.id]);
  return (
    <section className={styles.interactiveTerminal} aria-label="Interactive terminal">
      <div className={styles.terminalToolbar}>
        <h3>Shell</h3>
        <div className={styles.terminalActions} role="group" aria-label="Shell controls">
          <button
            aria-label="Open terminal"
            title="Open terminal"
            disabled={!lease}
            onClick={async () => {
              try {
                const result = await api<{ id: string }>(
                  `/api/bots/${botId}/sessions/${lease!.session_id}/terminals`,
                  { method: "POST", body: JSON.stringify(leaseBody(lease!)) },
                );
                setTerminalId(result.id);
                setError("");
              } catch (e) {
                setError(String(e));
              }
            }}
          >
            Open
          </button>
          <button
            title="Interrupt command (Ctrl+C)"
            disabled={!terminalId}
            onClick={() =>
              socketRef.current?.send(
                JSON.stringify({ op: "signal", signal: "INT" }),
              )
            }
          >
            Interrupt
          </button>
          <button
            aria-label="Close terminal"
            title="Close terminal"
            disabled={!terminalId}
            onClick={() => {
              socketRef.current?.close();
              setTerminalId(undefined);
            }}
          >
            Close
          </button>
        </div>
      </div>
      <p className={styles.terminalHint}>
        <span>{lease ? "Control enabled." : "Take control to open."}</span>
        <span>5m idle · 1h limit</span>
      </p>
      <div className={styles.terminalHost} ref={host} style={{ height: terminalId ? 320 : 0 }} />
      {error ? <p className={styles.terminalError} role="alert">{error}</p> : null}
    </section>
  );
}
