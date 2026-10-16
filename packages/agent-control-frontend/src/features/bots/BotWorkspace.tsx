import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { api, type BotDetail } from "../../api/client";
import { emptySession } from "../../session/reduce";
import { useSessionStore } from "../../session/store";
import { Dialog } from "../../components/ui/Dialog";
import { EmptyState } from "../../components/ui/EmptyState";
import { Icon } from "../../components/ui/Icon";
import { Composer } from "../chat/Composer";
import { Transcript } from "../chat/Transcript";
import { Workspace } from "../workspace/Workspace";
import { BotSettings } from "./BotSettings";
import { BotHeader } from "./BotHeader";
import { ChannelTaskNotice } from "./ChannelTaskNotice";
import { WindowsRecoveryNotice } from "../workspace/WindowsRecoveryNotice";
import styles from "../workspace/workspace.module.css";
import dialogStyles from "./dialog.module.css";

export function BotWorkspace() {
  const { id = "" } = useParams();
  const detail = useQuery({
    queryKey: ["bot", id],
    queryFn: () => api<BotDetail>(`/api/bots/${id}`),
    enabled: Boolean(id),
  });
  const seed = useSessionStore((state) => state.seed);
  useEffect(() => {
    if (detail.data) seed(detail.data.id, detail.data.messages);
  }, [detail.data, seed]);
  if (detail.isPending) return <EmptyState title="Opening bot…" />;
  if (detail.isError || !detail.data)
    return (
      <EmptyState title="Could not open this bot">
        <Link to="/overview">Return to your bots</Link>
      </EmptyState>
    );
  return <BotContent key={id} bot={detail.data} />;
}
function BotContent({ bot }: { bot: BotDetail }) {
  const session =
    useSessionStore((state) => state.sessions[bot.id]) ?? emptySession();
  const [params, setParams] = useSearchParams();
  const expanded = params.get("view") === "computer";
  const [settings, setSettings] = useState(false);
  return (
    <div className={styles.botPage}>
      <div
        className={`${styles.workspaceLayout} ${expanded ? styles.expandedLayout : ""}`}
      >
        {!expanded ? (
          <section
            className={styles.chat}
            aria-label={`${bot.name} conversation`}
          >
            <BotHeader
              bot={bot}
              session={session}
              onSettings={() => setSettings(true)}
              onComputer={() => setParams({ view: "computer", tab: "screen" })}
            />
            {session.status === "unknown" && !(["ufo", "open_interface"].includes(bot.framework) && session.computerStatus === "failed") ? (
              <p className={styles.notice} role="status">
                {session.protocol === 2
                  ? "The previous run was interrupted. Its outcome could not be confirmed."
                  : "Connection interrupted. The previous turn’s outcome is unknown. You can send a new message after reconnecting."}
              </p>
            ) : null}
            {session.computerStatus === "failed" ? (
              ["ufo", "open_interface"].includes(bot.framework) ? <WindowsRecoveryNotice macos={bot.framework === "open_interface"} botId={bot.id} session={session} /> :
              <p className={styles.notice} role="status">
                Sandbox recovery or termination is unverified. Close this sandbox before starting another task. Closing removes its workspace files.
              </p>
            ) : null}
            {session.status === "stopping" ? (
              <p className={styles.notice} role="status">
                Stopping. Waiting for sandbox operations to finish or confirm
                termination.
              </p>
            ) : null}
            <Transcript botId={bot.id} botName={bot.name} session={session} />
            <ChannelTaskNotice botId={bot.id} />
            <Composer
              botId={bot.id}
              botName={bot.name}
              defaultPrompt={bot.default_prompt}
              status={session.status}
              connection={session.connection}
            />
          </section>
        ) : null}
        <div className={expanded ? styles.expandedHost : styles.compactHost}>
          <Workspace
            bot={bot}
            session={session}
            expanded={expanded}
            onSettings={() => setSettings(true)}
          />
        </div>
      </div>
      <button
        className={styles.mobileComputer}
        onClick={() =>
          setParams(expanded ? {} : { view: "computer", tab: "screen" })
        }
      >
        <Icon name={expanded ? "back" : "computer"} />
        {expanded ? "Conversation" : "Open computer"}
      </button>
      <Dialog
        open={settings}
        onClose={() => setSettings(false)}
        title="Bot settings"
        className={dialogStyles.settingsDialog}
      >
        <BotSettings bot={bot} onSaved={() => setSettings(false)} />
      </Dialog>
    </div>
  );
}
