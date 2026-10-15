import type { ActivityEntry } from "../../session/reduce";
import { clockLabel } from "../../session/selectors";
import { EmptyState } from "../../components/ui/EmptyState";
import styles from "./workspace.module.css";
export function ActivityTimeline({
  entries,
  compact = false,
}: {
  entries: ActivityEntry[];
  compact?: boolean;
}) {
  if (entries.length === 0)
    return (
      <EmptyState icon="activity" title="No activity yet">
        Action, decision, and session events appear here.
      </EmptyState>
    );
  const shown = compact ? entries.slice(-8).reverse() : [...entries].reverse();
  return (
    <div className={styles.activityView}>
      {!compact ? (
        <p className={styles.activityIntro}>
          Available activity · Newest first
        </p>
      ) : null}
      <ol className={styles.timeline}>
        {shown.map((entry) => (
          <li key={entry.id} data-kind={entry.kind}>
            <div className={styles.eventTitle}>
              <strong>{entry.text}</strong>
              {entry.at !== undefined ? (
                <time dateTime={new Date(entry.at).toISOString()}>
                  {clockLabel(entry.at)}
                </time>
              ) : null}
            </div>
            {entry.detail ? (
              compact ? (
                <p className={styles.eventExcerpt}>{entry.detail}</p>
              ) : (
                <pre>{entry.detail}</pre>
              )
            ) : null}
          </li>
        ))}
      </ol>
    </div>
  );
}
