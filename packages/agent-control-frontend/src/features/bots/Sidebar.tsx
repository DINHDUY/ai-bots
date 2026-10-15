import { NavLink } from "react-router-dom";
import type { Bot } from "../../api/client";
import { Avatar } from "../../components/ui/Avatar";
import { Icon } from "../../components/ui/Icon";
import { pendingApprovals } from "../../session/reduce";
import { latestActivity, statusLabels } from "../../session/selectors";
import { useSessionStore } from "../../session/store";
import styles from "./sidebar.module.css";

export function Sidebar({
  bots,
  total,
  collapsed,
  onToggle,
  onCreate,
  folders = {},
  readCursors = {},
}: {
  bots: Bot[];
  total: number;
  collapsed: boolean;
  onToggle: () => void;
  onCreate: () => void;
  folders?: Record<string, string>;
  readCursors?: Record<string, number>;
}) {
  return (
    <aside className={styles.sidebar} aria-label="Workspace navigation">
      <div className={styles.railHeading}>
        <span className="eyebrow">Workspace</span>
        <button
          className="icon-button ghost"
          aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
          onClick={onToggle}
        >
          <Icon name="panel" />
        </button>
      </div>
      <NavLink
        className={styles.nav}
        to="/overview"
        title="Overview"
        aria-label="Overview"
      >
        <Icon name="grid" />
        <span>Overview</span>
        <small aria-hidden="true">{total}</small>
      </NavLink>
      <NavLink className={styles.nav} to="/channel" title="Bot channel" aria-label="Bot channel"><Icon name="share" /><span>Bot channel</span></NavLink>
      <div className={styles.section}>
        <span className="eyebrow">Your bots / {total}</span>
        <button
          className="icon-button ghost"
          onClick={onCreate}
          aria-label="Add a bot"
        >
          <Icon name="plus" />
        </button>
      </div>
      <nav className={styles.list} aria-label="Bots">
        {[...new Set(bots.map((bot) => folders[bot.id] || ""))].map(
          (folder) => (
            <div key={folder}>
              {folder && !collapsed ? (
                <p className="eyebrow">{folder}</p>
              ) : null}
              {bots
                .filter((bot) => (folders[bot.id] || "") === folder)
                .map((bot) => (
                  <BotLink
                    key={bot.id}
                    bot={bot}
                    readCursor={readCursors[bot.id]}
                  />
                ))}
            </div>
          ),
        )}
        {bots.length === 0 ? (
          <p className={styles.empty}>
            {total ? "No matching bots." : "Create a bot to get started."}
          </p>
        ) : null}
      </nav>
      <div className={styles.bottom}>
        <NavLink className={styles.nav} to="/keys" title="API keys">
          <Icon name="lock" />
          <span>API keys</span>
        </NavLink>
        <div className={styles.note}>
          <Icon name="shield" />
          <div>
            <strong>Your private workspace</strong>
            <p>Manage bot conversations and workspace computers.</p>
          </div>
        </div>
        <div className={styles.foot}>
          <Icon name="cloud" />
          <span>Agent Control</span>
        </div>
      </div>
    </aside>
  );
}
function BotLink({ bot, readCursor }: { bot: Bot; readCursor?: number }) {
  const session = useSessionStore((state) => state.sessions[bot.id]);
  const status = session?.status ?? "idle";
  const autopilot = session?.autopilot?.enabled === true;
  const waiting = session ? pendingApprovals(session).length : 0;
  const statusLabel =
    status === "awaiting" ? "Approval" : status === "unknown" ? "Unknown" : statusLabels[status];
  const approvalCount = waiting > 1 ? ` (${waiting})` : "";
  const description = `${bot.name} · ${statusLabels[status]}${approvalCount}${autopilot ? " · Autopilot on" : ""}`;
  const unread =
    readCursor === undefined
      ? 0
      : (session?.items.filter(
          (item) => item.kind === "assistant" && (item.order ?? 0) > readCursor,
        ).length ?? 0);
  return (
    <NavLink
      className={styles.bot}
      to={`/bots/${bot.id}`}
      aria-label={description}
      title={`${description}\n${latestActivity(session)}`}
    >
      <Avatar name={bot.name} id={bot.id} />
      <span className={styles.detail}>
        <strong>{bot.name}</strong>
        <span className={styles.statusRow}>
          <span className={styles.status} data-status={status}>
            {statusLabel}{approvalCount}
          </span>
          {autopilot ? <span className={styles.autopilot}>Autopilot</span> : null}
        </span>
      </span>
      {autopilot ? (
        <span className={styles.autopilotMarker} aria-hidden="true">
          <Icon name="spark" />
        </span>
      ) : null}
      {waiting > 0 ? <i className={styles.waitingDot} aria-hidden="true" /> : null}
      {unread > 0 ? (
        <small aria-label={`${unread} unread messages`}>{unread}</small>
      ) : null}
    </NavLink>
  );
}
