import type { Bot } from "../../api/client";
import { AutopilotBadge } from "./AutopilotToggle";
import type { BotSession } from "../../session/reduce";
import { Avatar } from "../../components/ui/Avatar";
import { Icon } from "../../components/ui/Icon";
import { StatusBadge } from "../../components/ui/StatusBadge";
import styles from "../workspace/workspace.module.css";
export function BotHeader({
  bot,
  session,
  onSettings,
  onComputer,
}: {
  bot: Bot;
  session: BotSession;
  onSettings: () => void;
  onComputer: () => void;
}) {
  return (
    <header className={styles.botHeader}>
      <Avatar name={bot.name} id={bot.id} />
      <div className={styles.botIdentity}>
        <div className="row">
          <h1>{bot.name}</h1>
          <StatusBadge status={session.status} label={["ufo", "open_interface"].includes(bot.framework) && session.computerStatus === "failed" ? "Recovery required" : undefined} />
        </div>
        <p><AutopilotBadge enabled={session.autopilot?.enabled} /> {bot.model || bot.framework} · Your persistent agent workspace</p>
      </div>
      <span className="spacer" />
      <button
        className="icon-button ghost"
        aria-label="Open cloud computer"
        onClick={onComputer}
      >
        <Icon name="computer" />
      </button>
      <button
        className="icon-button ghost"
        aria-label="Bot settings"
        onClick={onSettings}
      >
        <Icon name="settings" />
      </button>
    </header>
  );
}
