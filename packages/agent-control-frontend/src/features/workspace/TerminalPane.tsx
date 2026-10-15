import { lazy, Suspense, useLayoutEffect, useRef, useState } from "react";
import type { TerminalEntry } from "../../session/reduce";
import { emptyView, useWorkspaceUi } from "../../session/workspaceUiStore";
import { EmptyState } from "../../components/ui/EmptyState";
import { CopyButton } from "../../components/ui/CopyButton";
import { Icon } from "../../components/ui/Icon";
import styles from "./workspace.module.css";
import { useSessionStore } from "../../session/store";
const InteractiveTerminal = lazy(() =>
  import("./InteractiveTerminal").then((module) => ({
    default: module.InteractiveTerminal,
  })),
);
export function TerminalPane({
  botId,
  entries,
  compact = false,
}: {
  botId: string;
  entries: TerminalEntry[];
  compact?: boolean;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const pty = useSessionStore(
    (state) => state.sessions[botId]?.health?.services.terminal,
  );
  const view = useWorkspaceUi.getState().bots[botId] ?? emptyView;
  const follow = useRef(compact || view.terminalFollow);
  const [unread, setUnread] = useState(false);
  const count = useRef(entries.length);
  useLayoutEffect(() => {
    if (!compact && ref.current && view.terminalTop !== undefined)
      ref.current.scrollTop = view.terminalTop;
  }, [botId, compact]);
  useLayoutEffect(() => {
    if (ref.current && follow.current)
      ref.current.scrollTop = ref.current.scrollHeight;
    else if (entries.length !== count.current) setUnread(true);
    count.current = entries.length;
  }, [entries]);
  const visible = compact ? entries.slice(-1) : entries;
  return (
    <section
      className={`${styles.terminal} ${compact ? styles.compactTerminal : ""}`}
      aria-label="Terminal output"
    >
      {!compact && pty ? (
        <Suspense fallback={<p>Loading terminal…</p>}>
          <InteractiveTerminal botId={botId} />
        </Suspense>
      ) : null}
      <div className={styles.terminalHeader}>
        <Icon name="terminal" />
        <h3>{!compact && pty ? "Command output" : "Terminal"}</h3>
        <span className="spacer" />
        {!compact && entries.length > 0 ? (
          <CopyButton
            label="Copy output"
            text={entries
              .map((entry) => `$ ${entry.command}\n${entry.output}`)
              .join("\n\n")}
          />
        ) : !compact && pty ? null : (
          <span>Command results</span>
        )}
      </div>
      <div
        ref={ref}
        className={styles.terminalBody}
        tabIndex={0}
        onScroll={(event) => {
          if (compact) return;
          const el = event.currentTarget;
          follow.current =
            el.scrollHeight - el.scrollTop - el.clientHeight < 40;
          if (follow.current) setUnread(false);
          useWorkspaceUi.getState().patch(botId, {
            terminalTop: el.scrollTop,
            terminalFollow: follow.current,
          });
        }}
      >
        {entries.length === 0 ? (
          <EmptyState icon="terminal" title="No terminal output yet">
            Command results appear here after execution.
          </EmptyState>
        ) : (
          visible.map((entry) => (
            <div key={entry.id} className={styles.terminalEntry}>
              <p>
                <span>$</span> {entry.command}
              </p>
              {entry.outcome ? <p role="status">{entry.outcome}</p> : null}
              {entry.output ? (
                <pre>{entry.output}</pre>
              ) : (
                <p className={styles.outputEmpty}>No output reported.</p>
              )}
            </div>
          ))
        )}
      </div>
      {unread && !compact ? (
        <button
          className={styles.followButton}
          onClick={() => {
            if (ref.current) ref.current.scrollTop = ref.current.scrollHeight;
            follow.current = true;
            setUnread(false);
            useWorkspaceUi.getState().patch(botId, { terminalFollow: true });
          }}
        >
          Follow latest output
        </button>
      ) : null}
    </section>
  );
}
