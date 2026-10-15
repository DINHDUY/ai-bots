import type { BotSession } from "../../session/reduce";
import { ComputerDisconnect } from "./ComputerDisconnect";
import styles from "./workspace.module.css";

export function WindowsRecoveryNotice({ botId, session }: { botId: string; session: BotSession }) {
  return <div className={`${styles.notice} ${styles.recoveryNotice}`} aria-label="Windows recovery required">
    <p role="status"><strong>Recovery required.</strong> An earlier Windows action has an unconfirmed outcome. A ready companion does not clear this bot's interrupted task.</p>
    <p>Inspect the application, disconnect this bot, then select <strong>Connect Windows PC</strong>. Enable local control and send a new task describing the current state. Your PC, applications, and files remain.</p>
    <ComputerDisconnect botId={botId} session={session} windows recovery />
  </div>;
}
