import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import type { Bot } from "../../api/client";
import { pendingApprovals, type BotSession } from "../../session/reduce";
import { Icon } from "../../components/ui/Icon";
import { StatusBadge } from "../../components/ui/StatusBadge";
import styles from "./workspace.module.css";
import { ComputerControls } from "./ComputerControls";
import { AutopilotBadge } from "../bots/AutopilotToggle";
import { ComputerDisconnect } from "./ComputerDisconnect";
import { useComputerControl } from "./useComputerControl";

export function WorkspaceHeader({
  bot,
  session,
  expanded,
  onSettings,
}: {
  bot: Bot;
  session: BotSession;
  expanded: boolean;
  onSettings: () => void;
}) {
  const [params, setParams] = useSearchParams();
  const waiting = pendingApprovals(session).length;
  const macos = bot.framework === "open_interface";
  const windows = bot.framework === "ufo" || macos;
  const { report } = useComputerControl(bot.id, session.protocol === 2);
  const cloud = report.data?.provider?.startsWith("azure_");
  const shared = report.data?.workspace_computer === true;
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 10000);
    return () => clearInterval(timer);
  }, []);
  const health =
    session.health && now - Date.parse(session.health.observed_at) < 30000
      ? session.health.health
      : "unknown";
  const connection =
    session.connection === "connected"
      ? "Connected to control"
      : session.connection === "reconnecting"
        ? "Reconnecting"
        : session.connection === "connecting"
          ? "Connecting"
          : "Disconnected";
  return (
    <header className={styles.workspaceHeader}>
      <div className={styles.workspaceHeading}>
        {expanded ? (
          <Link className={styles.back} to={`/bots/${bot.id}`}>
            <Icon name="back" />
            <span>Workspace</span>
          </Link>
        ) : null}
        <div className={styles.computerIdentity}>
          <div className={styles.computerTitle}>
            <Icon name="computer" />
            <h2>{shared ? "Shared workspace computer" : macos ? "Local Mac" : windows ? "Local Windows PC" : report.data?.display_name ?? "Live Cloud Computer"}</h2>
          </div>
          <p className={styles.sessionIdentity} title={session.sessionId}>
            {shared
              ? `Shared by ${report.data?.computer?.attached_bot_ids?.length ?? 0} bots`
              : session.sessionId ?? (cloud ? "Attach or start a computer in Bot settings" : "Session starts with your first message")}
          </p>
          <div className={styles.computerStatus}>
            <AutopilotBadge enabled={session.autopilot?.enabled} />
            <span
              className={styles.connection}
              data-connected={session.connection === "connected"}
            >
              <i className="dot" />
              {connection}
            </span>
            {session.protocol === 2 ? (
              <span
                className={styles.computerHealth}
                aria-label="Computer health"
              >
                {windows ? "Desktop health:" : "Sandbox health:"} {health}
              </span>
            ) : null}
          </div>
        </div>
        <div className={styles.workspaceActions}>
          {expanded ? (
            <>
              <StatusBadge status={session.status} label={windows && session.computerStatus === "failed" ? "Recovery required" : undefined} />
              {waiting ? (
                <Link className={styles.approvalLink} to={`/bots/${bot.id}`}>
                  <Icon name="shield" />
                  Review {waiting} approval{waiting === 1 ? "" : "s"}
                </Link>
              ) : null}
              <button
                className="icon-button ghost"
                aria-label="Bot settings"
                onClick={onSettings}
              >
                <Icon name="settings" />
              </button>
            </>
          ) : (
            <button
              className="icon-button ghost"
              aria-label={macos ? "Expand macOS desktop" : windows ? "Expand Windows desktop" : "Expand cloud computer"}
              onClick={() => {
                const next = new URLSearchParams(params);
                next.set("view", "computer");
                setParams(next);
              }}
            >
              <Icon name="expand" />
            </button>
          )}
          {!cloud && !shared ? <ComputerDisconnect botId={bot.id} session={session} windows={windows} macos={macos} /> : null}
        </div>
      </div>
      {session.protocol === 2 ? <ComputerControls botId={bot.id} /> : null}
    </header>
  );
}
