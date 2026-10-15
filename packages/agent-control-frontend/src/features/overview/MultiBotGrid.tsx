import { CaptureImage } from "../../components/ui/CaptureImage";
import { Link } from "react-router-dom";
import type { Bot } from "../../api/client";
import { pendingApprovals } from "../../session/reduce";
import { useSessionStore } from "../../session/store";
import { Avatar } from "../../components/ui/Avatar";
import { Icon } from "../../components/ui/Icon";
import { StatusBadge } from "../../components/ui/StatusBadge";
import { EmptyState } from "../../components/ui/EmptyState";
import { ApprovalCard } from "../chat/ApprovalCard";
import styles from "./overview.module.css";
export function MultiBotGrid({
  bots,
  onCreate,
}: {
  bots: Bot[];
  onCreate: () => void;
}) {
  return (
    <div className={styles.page}>
      <header className={styles.heading}>
        <div>
          <p className="eyebrow">Your workspace</p>
          <h1>A clear view of every bot.</h1>
          <p className="muted">
            Follow their work, review actions, and pick up a conversation.
          </p>
        </div>
        <span className="badge">
          {bots.length} bot{bots.length === 1 ? "" : "s"}
        </span>
      </header>
      {bots.length === 0 ? (
        <div className={styles.start}>
          <EmptyState icon="spark" title="Your first bot starts here">
            Give your bot a task and a cloud workspace of its own.
          </EmptyState>
          <button className="primary" onClick={onCreate}>
            <Icon name="plus" />
            Create your first bot
          </button>
        </div>
      ) : (
        <div className={styles.grid}>
          {bots.map((bot) => (
            <Tile key={bot.id} bot={bot} />
          ))}
        </div>
      )}
    </div>
  );
}
function Tile({ bot }: { bot: Bot }) {
  const session = useSessionStore((state) => state.sessions[bot.id]);
  const decide = useSessionStore((state) => state.decide);
  const status = session?.status ?? "idle";
  const shot = session?.shots.at(-1);
  const waiting = session ? pendingApprovals(session) : [];
  return (
    <article className={styles.tile}>
      <div className={styles.tileHeader}>
        <Avatar name={bot.name} id={bot.id} />
        <div>
          <h2>
            <Link to={`/bots/${bot.id}`}>{bot.name}</Link>
          </h2>
          <p>{bot.model || bot.framework}</p>
        </div>
        <span className="spacer" />
        <StatusBadge status={status} />
      </div>
      <Link
        className={styles.capture}
        to={`/bots/${bot.id}?view=computer&tab=screen`}
      >
        {shot ? (
          <CaptureImage
            expiresAt={shot.expiresAt}
            onUnavailable={() => useSessionStore.getState().removeCapture(bot.id, shot.id)}
            alt={`Latest observed capture from ${bot.name}`}
            src={shot.src}
          />
        ) : (
          <EmptyState icon="computer" title="Awaiting a capture">
            Your bot’s screen will appear here.
          </EmptyState>
        )}
      </Link>
      <p className={styles.captureLabel}>
        {status === "closed" ||
        status === "unknown" ||
        session?.connection !== "connected"
          ? "Previous observation · Current state unverified"
          : shot
            ? "Latest observed capture"
            : "Ready for a task"}
      </p>
      {waiting.map((item) => (
        <ApprovalCard
          botId={bot.id}
          submitting={session?.submittingApprovalId === item.approvalId}
          key={item.approvalId}
          item={item}
          disabled={session?.connection !== "connected" || session?.submitting}
          onAllow={() => decide(bot.id, item.approvalId, "approve")}
          onDeny={() => decide(bot.id, item.approvalId, "deny")}
        />
      ))}
      <Link className={styles.open} to={`/bots/${bot.id}`}>
        Open conversation
        <Icon name="arrow" />
      </Link>
    </article>
  );
}
