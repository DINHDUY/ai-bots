import { Link } from "react-router-dom";
import type { Bot } from "../../api/client";
import { pendingApprovals, type BotSession } from "../../session/reduce";
import { Avatar } from "../../components/ui/Avatar";
import { Icon } from "../../components/ui/Icon";
import { StatusBadge } from "../../components/ui/StatusBadge";
import { ActivityTimeline } from "./ActivityTimeline";
import styles from "./workspace.module.css";
export function SessionContext({
  bot,
  session,
}: {
  bot: Bot;
  session: BotSession;
}) {
  const waiting = pendingApprovals(session).length;
  return (
    <aside className={styles.inspector} aria-label="Session context">
      <h2>Session context</h2>
      <div className={styles.sessionCard}>
        <div className="row">
          <Avatar name={bot.name} id={bot.id} />
          <div>
            <h3>{bot.name}</h3>
            <p>{bot.framework}</p>
          </div>
        </div>
        <p>{bot.model || "Agent model"}</p>
        <StatusBadge status={session.status} />
      </div>
      <dl className={styles.sessionDetails}>
        {session.health?.started_at ? <div><dt>Sandbox started</dt><dd>{new Date(session.health.started_at).toLocaleString()}</dd></div> : null}
        {session.health ? <div><dt>Service health observed</dt><dd>{new Date(session.health.observed_at).toLocaleTimeString()}</dd></div> : null}
        <div>
          <dt>Connection</dt>
          <dd>{session.connection}</dd>
        </div>
        <div>
          <dt>Captures retained</dt>
          <dd>{session.shots.length}</dd>
        </div>
        <div>
          <dt>File observations</dt>
          <dd>{session.files.length}</dd>
        </div>
        <div>
          <dt>Activity history</dt>
          <dd>
            {session.protocol === 2
              ? "Retained server events"
              : "This page session"}
          </dd>
        </div>
      </dl>
      {session.observationsTruncated ? (
        <p className="muted">
          Showing recent retained observations. Earlier messages can be loaded
          in the conversation.
        </p>
      ) : null}
      {waiting ? (
        <Link className={styles.reviewBanner} to={`/bots/${bot.id}`}>
          <Icon name="shield" />
          {waiting} approval{waiting === 1 ? "" : "s"} needs review
          <Icon name="arrow" />
        </Link>
      ) : null}
      {session.plan ? (
        <section aria-label="Task plan">
          <h2>Task plan</h2>
          <p>
            {session.plan.filter((step) => step.status === "completed").length}{" "}
            of {session.plan.length} steps completed
          </p>
          <ol>
            {session.plan.map((step) => (
              <li key={step.id}>
                {step.title} · {step.status}
              </li>
            ))}
          </ol>
        </section>
      ) : (
        <p className="muted">
          Task progress is indeterminate until the agent supplies an explicit
          plan.
        </p>
      )}
      <h2 className={styles.activityHeading}>Activity</h2>
      <div className={styles.inspectorActivity}>
        <ActivityTimeline entries={session.activity} compact />
      </div>
      <Link className={styles.returnChat} to={`/bots/${bot.id}`}>
        <Icon name="bot" />
        <span>Continue in conversation</span>
        <Icon name="arrow" />
      </Link>
    </aside>
  );
}
