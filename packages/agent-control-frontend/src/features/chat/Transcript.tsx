import {
  lazy,
  Suspense,
  useCallback,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
} from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../../api/client";
import { ApprovalCard } from "./ApprovalCard";
import type { BotSession } from "../../session/reduce";
import { useSessionStore } from "../../session/store";
import { emptyView, useWorkspaceUi } from "../../session/workspaceUiStore";
import { clockLabel } from "../../session/selectors";
import { Avatar } from "../../components/ui/Avatar";
import { EmptyState } from "../../components/ui/EmptyState";
import { Icon } from "../../components/ui/Icon";
import styles from "./chat.module.css";

const MessageContent = lazy(() => import("./MessageContent"));

export function Transcript({
  botId,
  botName,
  session,
}: {
  botId: string;
  botName: string;
  session: BotSession;
}) {
  const decide = useSessionStore((state) => state.decide);
  const loadEarlier = useSessionStore((state) => state.loadEarlier);
  const [loadingEarlier, setLoadingEarlier] = useState(false);
  const [historyError, setHistoryError] = useState("");
  const ref = useRef<HTMLDivElement>(null);
  const initial = useWorkspaceUi.getState().bots[botId] ?? emptyView;
  const follow = useRef(initial.transcriptFollow);
  const [newItems, setNewItems] = useState(false);
  const lastCount = useRef(session.items.length);
  const queryClient = useQueryClient();
  const capabilities = useQuery({
    queryKey: ["capabilities"],
    queryFn: () => api<{ workspaces?: boolean }>("/api/capabilities"),
    staleTime: 60000,
    retry: false,
  });
  const messageSequence = Math.max(
    0,
    ...session.items
      .filter((item) => item.kind === "assistant" || item.kind === "user")
      .map((item) => item.order ?? 0),
  );
  useEffect(() => {
    if (
      session.protocol !== 2 ||
      !messageSequence ||
      !follow.current ||
      document.visibilityState !== "visible"
    )
      return;
    const preferences = queryClient.getQueryData<{
      read_cursors?: Record<string, number>;
    }>(["preferences"]);
    if (
      !capabilities.data?.workspaces ||
      (preferences?.read_cursors?.[botId] ?? 0) >= messageSequence
    )
      return;
    const timer = window.setTimeout(() => {
      if (!follow.current || document.visibilityState !== "visible") return;
      void api(`/api/bots/${botId}/read-cursor`, {
        method: "POST",
        body: JSON.stringify({ sequence: messageSequence }),
      })
        .then((data) => queryClient.setQueryData(["preferences"], data))
        .catch(() => {});
    }, 500);
    return () => window.clearTimeout(timer);
  }, [
    botId,
    messageSequence,
    newItems,
    queryClient,
    session.protocol,
    capabilities.data?.workspaces,
  ]);
  const contentRendered = useCallback(() => {
    if (ref.current && follow.current)
      ref.current.scrollTop = ref.current.scrollHeight;
  }, []);
  useLayoutEffect(() => {
    if (ref.current && initial.transcriptTop !== undefined)
      ref.current.scrollTop = initial.transcriptTop;
    // Restore only when this bot's transcript mounts.
  }, [botId]);
  useLayoutEffect(() => {
    const element = ref.current;
    if (element && follow.current) element.scrollTop = element.scrollHeight;
    else if (lastCount.current !== session.items.length) setNewItems(true);
    lastCount.current = session.items.length;
  }, [session.items]);
  function jump() {
    if (ref.current) ref.current.scrollTop = ref.current.scrollHeight;
    follow.current = true;
    setNewItems(false);
    useWorkspaceUi.getState().patch(botId, { transcriptFollow: true });
  }
  return (
    <div className={styles.threadWrapper}>
      <div
        ref={ref}
        className={styles.thread}
        tabIndex={0}
        aria-label="Conversation messages"
        onScroll={(event) => {
          const el = event.currentTarget;
          follow.current =
            el.scrollHeight - el.scrollTop - el.clientHeight < 60;
          useWorkspaceUi.getState().patch(botId, {
            transcriptTop: el.scrollTop,
            transcriptFollow: follow.current,
          });
          if (follow.current) setNewItems(false);
        }}
      >
        {session.messagesBefore ? (
          <button
            disabled={loadingEarlier}
            onClick={async () => {
              const oldHeight = ref.current?.scrollHeight ?? 0;
              const oldTop = ref.current?.scrollTop ?? 0;
              follow.current = false;
              setLoadingEarlier(true);
              setHistoryError("");
              try {
                await loadEarlier(botId);
                lastCount.current =
                  useSessionStore.getState().sessions[botId]?.items.length ?? 0;
                requestAnimationFrame(() => {
                  if (ref.current)
                    ref.current.scrollTop =
                      oldTop + ref.current.scrollHeight - oldHeight;
                });
              } catch {
                setHistoryError("Earlier messages could not be loaded.");
              } finally {
                setLoadingEarlier(false);
              }
            }}
          >
            {loadingEarlier
              ? "Loading earlier messages…"
              : "Load earlier messages"}
          </button>
        ) : null}
        {historyError ? <p role="alert">{historyError}</p> : null}
        {session.items.length === 0 ? (
          <EmptyState icon="spark" title={`What should ${botName} work on?`}>
            Describe a task below. Follow the activity in the cloud computer and
            review actions as they come up.
          </EmptyState>
        ) : (
          <div className={styles.separator}>Conversation</div>
        )}
        {session.items.map((item) => {
          if (item.kind === "thought")
            return (
              <details key={item.id} className={styles.thought}>
                <summary>
                  <Icon name="spark" />
                  Thinking
                </summary>
                <p>{item.text}</p>
              </details>
            );
          if (item.kind === "approval")
            return (
              <div key={item.id} className={styles.approvalWrap}>
                <ApprovalCard
                  botId={botId}
                  submitting={session.submittingApprovalId === item.approvalId}
                  item={item}
                  disabled={
                    session.connection !== "connected" || session.submitting
                  }
                  onAllow={() => decide(botId, item.approvalId, "approve")}
                  onDeny={() => decide(botId, item.approvalId, "deny")}
                />
              </div>
            );
          const user = item.kind === "user";
          return (
            <article
              key={item.id}
              className={`${styles.message} ${styles[item.kind]}`}
            >
              {!user ? <Avatar name={botName} id={botId} /> : null}
              <div className={styles.messageBody}>
                <div className={styles.meta}>
                  <strong>
                    {user
                      ? "You"
                      : item.kind === "system"
                        ? "Session"
                        : item.kind === "error"
                          ? "Error"
                          : botName}
                  </strong>
                  {item.at !== undefined ? (
                    <time dateTime={new Date(item.at).toISOString()}>
                      {clockLabel(item.at)}
                    </time>
                  ) : null}
                </div>
                <div className={styles.messageText}>
                  <Suspense fallback={<p>{item.text}</p>}>
                    <MessageContent
                      text={item.text}
                      onRendered={contentRendered}
                    />
                  </Suspense>
                </div>
              </div>
            </article>
          );
        })}
      </div>
      {newItems ? (
        <button className={styles.newMessages} onClick={jump}>
          <Icon name="chevron" />
          New messages
        </button>
      ) : null}
      <span className="sr-only" role="status">
        {session.status === "awaiting"
          ? "An action needs your approval."
          : session.status === "running"
            ? "Your bot is working."
            : session.status === "error"
              ? "Your bot reported an error."
              : ""}
      </span>
    </div>
  );
}
