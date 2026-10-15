import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import type { BotSession } from "../../session/reduce";
import { useSessionStore } from "../../session/store";
import { Dialog } from "../../components/ui/Dialog";
import { Icon } from "../../components/ui/Icon";
import styles from "./workspace.module.css";

export function ComputerDisconnect({ botId, session, windows, recovery = false }: {
  botId: string;
  session: BotSession;
  windows: boolean;
  recovery?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const client = useQueryClient();
  const closeSandbox = useSessionStore((state) => state.closeSandbox);
  const label = recovery ? "Review and disconnect" : windows ? "Disconnect Windows PC" : "Close sandbox";
  async function disconnect() {
    setBusy(true);
    setError("");
    try {
      if (await closeSandbox(botId)) {
        await client.invalidateQueries({ queryKey: ["computer", botId] });
        await client.invalidateQueries({ queryKey: ["control", botId] });
        setOpen(false);
      } else {
        setError(useSessionStore.getState().sessions[botId]?.commandError || "Disconnect was not accepted. Check the connection and try again.");
      }
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setBusy(false);
    }
  }
  return <>
    <button
      type="button"
      className={recovery ? "" : "icon-button ghost"}
      title={label}
      aria-label={label}
      disabled={busy || session.submitting || !session.controlBound || session.connection !== "connected" || session.status === "closed"}
      onClick={() => { setError(""); setOpen(true); }}
    >
      {recovery ? label : <Icon name="close" />}
    </button>
    <Dialog open={open} title={windows ? "Disconnect Windows PC?" : "Close sandbox?"} onClose={() => { if (!busy) setOpen(false); }}>
      <div className={styles.closeDialog}>
        <p>{windows ? "This stops automation and disconnects this bot from your PC. Your Windows applications and files remain." : "This stops the bot and removes its sandbox, including all workspace files. Your bot and conversation remain."}</p>
        <p className="muted">{windows ? "Inspect any interrupted action before reconnecting and enabling control locally." : "The next message starts a fresh workspace."}</p>
        {error ? <p role="alert" className="error">{error}</p> : null}
        <div className="row">
          <span className="spacer" />
          <button disabled={busy} onClick={() => setOpen(false)}>Keep open</button>
          <button className="danger" disabled={busy} onClick={() => void disconnect()}>
            {busy ? (windows ? "Disconnecting…" : "Closing…") : windows ? "Disconnect PC" : "Close sandbox"}
          </button>
        </div>
      </div>
    </Dialog>
  </>;
}
