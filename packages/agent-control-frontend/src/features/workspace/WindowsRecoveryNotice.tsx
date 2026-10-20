import type { BotSession } from "../../session/reduce";
import { ComputerDisconnect } from "./ComputerDisconnect";
import styles from "./workspace.module.css";

export function WindowsRecoveryNotice({ botId, session, macos = false }: { botId: string; session: BotSession; macos?: boolean }) {
  return <div className={`${styles.notice} ${styles.recoveryNotice}`} aria-label={macos ? "Mac recovery required" : "Windows recovery required"}>
    <p role="status"><strong>Recovery required.</strong> An earlier {macos ? "Mac" : "Windows"} action has an unconfirmed outcome. A ready companion does not clear this bot's interrupted task.</p>
    <p>Inspect the application, disconnect this bot, then select <strong>{macos ? "Connect Mac" : "Connect Windows PC"}</strong>. Enable local control and send a new task describing the current state. Your PC, applications, and files remain.</p>
    <ComputerDisconnect botId={botId} session={session} windows macos={macos} recovery />
  </div>;
}
