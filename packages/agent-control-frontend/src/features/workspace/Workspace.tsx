import { useSearchParams } from "react-router-dom";
import type { Bot } from "../../api/client";
import type { BotSession } from "../../session/reduce";
import { observedFiles } from "../../session/selectors";
import { Icon } from "../../components/ui/Icon";
import { useWorkspaceUi } from "../../session/workspaceUiStore";
import { LiveScreen } from "./LiveScreen";
import { TerminalPane } from "./TerminalPane";
import { FilesPane } from "./FilesPane";
import { ActivityTimeline } from "./ActivityTimeline";
import { WorkspaceHeader } from "./WorkspaceHeader";
import { SessionContext } from "./SessionContext";
import { WindowsRecoveryNotice } from "./WindowsRecoveryNotice";
import styles from "./workspace.module.css";

const TABS = [
  { id: "screen", label: "Screen", icon: "browser" },
  { id: "terminal", label: "Terminal", icon: "terminal" },
  { id: "files", label: "Filesystem", icon: "folder" },
  { id: "activity", label: "Activity", icon: "activity" },
] as const;
export function Workspace({
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
  const windows = bot.framework === "ufo";
  const tabs = windows ? TABS.filter(t => t.id === "screen" || t.id === "activity") : TABS;
  const patchView = useWorkspaceUi((state) => state.patch);
  const tab =
    tabs.find((item) => item.id === params.get("tab"))?.id ?? "screen";
  const split =
    !windows && expanded && tab === "screen" && params.get("layout") !== "single";
  const stale =
    session.sandboxClosed ||
    !session.controlBound ||
    session.status === "unknown" ||
    session.connection !== "connected";
  function select(id: string) {
    const next = new URLSearchParams(params);
    next.set("tab", id);
    setParams(next);
  }
  const recent = observedFiles(session.files).slice(-3);
  return (
    <section
      className={`${styles.workspace} ${expanded ? styles.expanded : styles.compact}`}
      aria-label={windows ? "Local Windows PC" : "Live Cloud Computer"}
    >
      <WorkspaceHeader
        bot={bot}
        session={session}
        expanded={expanded}
        onSettings={onSettings}
      />
      {expanded && windows && session.computerStatus === "failed" ? <WindowsRecoveryNotice botId={bot.id} session={session} /> : null}
      <div className={styles.computerBody}>
        <div className={styles.stage}>
          <div className={styles.toolbar}>
            <div
              className={styles.tabs}
              role="tablist"
              aria-label="Computer views"
            >
              {tabs.map((item, index) => (
                <button
                  key={item.id}
                  type="button"
                  role="tab"
                  id={`tab-${bot.id}-${item.id}`}
                  aria-selected={tab === item.id}
                  aria-controls={`computer-panel-${bot.id}`}
                  tabIndex={tab === item.id ? 0 : -1}
                  onClick={() => select(item.id)}
                  onKeyDown={(event) => {
                    const next =
                      event.key === "ArrowRight"
                        ? (index + 1) % tabs.length
                        : event.key === "ArrowLeft"
                          ? (index + tabs.length - 1) % tabs.length
                          : event.key === "Home"
                            ? 0
                            : event.key === "End"
                              ? tabs.length - 1
                              : -1;
                    if (next >= 0) {
                      event.preventDefault();
                      select(tabs[next].id);
                      document
                        .getElementById(`tab-${bot.id}-${tabs[next].id}`)
                        ?.focus();
                    }
                  }}
                >
                  <Icon name={item.icon} />
                  <span>{item.label}</span>
                </button>
              ))}
            </div>
            {!windows && expanded && tab === "screen" ? (
              <button
                className="icon-button ghost"
                title={split ? "Show screen only" : "Show screen and terminal"}
                aria-label={
                  split ? "Show screen only" : "Show screen and terminal"
                }
                onClick={() => {
                  const next = new URLSearchParams(params);
                  next.set("layout", split ? "single" : "split");
                  setParams(next);
                }}
              >
                <Icon name={split ? "expand" : "split"} />
              </button>
            ) : null}
          </div>
          <div
            id={`computer-panel-${bot.id}`}
            role="tabpanel"
            aria-labelledby={`tab-${bot.id}-${tab}`}
            tabIndex={0}
            className={`${styles.paneBody} ${split ? styles.splitBody : ""}`}
          >
            {session.status === "closed" ? (
              <p className={styles.notice}>
                {windows ? "Windows PC disconnected. Captures below are historical." : "Sandbox closed. Captures and previews below are historical; the workspace was removed."}
              </p>
            ) : stale && session.sessionId ? (
              <p className={styles.notice}>
                Showing previous observations. Current sandbox state is
                unverified.
              </p>
            ) : null}
            {tab === "screen" ? (
              <>
                <LiveScreen
                  windows={windows}
                  botId={bot.id}
                  shots={session.shots}
                  dropped={session.droppedShots}
                  historical={stale}
                />
                <div
                  className={
                    split ? styles.splitTerminal : styles.terminalExcerpt
                  }
                >
                  {!windows && (split || !expanded) ? (
                    <TerminalPane
                      key={split ? "split" : "compact"}
                      botId={bot.id}
                      entries={session.terminal}
                      compact={!expanded}
                    />
                  ) : null}
                </div>
                {!expanded && recent.length > 0 ? (
                  <section className={styles.recentFiles}>
                    <div className="row">
                      <h3>Observed files</h3>
                      <span className="spacer" />
                      <button className="ghost" onClick={() => select("files")}>
                        View all <Icon name="arrow" />
                      </button>
                    </div>
                    {recent.map((file) => (
                      <button
                        key={file.path}
                        onClick={() => {
                          patchView(bot.id, { filePath: file.path });
                          select("files");
                        }}
                      >
                        <Icon name="file" />
                        <span>
                          {file.path.replaceAll("\\", "/").split("/").at(-1)}
                        </span>
                        <small>Preview</small>
                      </button>
                    ))}
                  </section>
                ) : null}
              </>
            ) : null}
            {tab === "terminal" ? (
              <TerminalPane botId={bot.id} entries={session.terminal} />
            ) : null}
            {tab === "files" ? (
              <FilesPane
                botId={bot.id}
                files={session.files}
                expanded={expanded}
              />
            ) : null}
            {tab === "activity" ? (
              <ActivityTimeline entries={session.activity} />
            ) : null}
          </div>
          <footer className={styles.workspaceFooter}>
            <span>
              <Icon name="cloud" />
              Powered by <code>{windows ? "Microsoft UFO" : "agentbot_sandbox"}</code>
            </span>
            {expanded ? <span>Observations from this page session</span> : null}
          </footer>
        </div>
        {expanded ? <SessionContext bot={bot} session={session} /> : null}
      </div>
    </section>
  );
}
