import { Link } from "react-router-dom";
import { useComputerControl } from "../workspace/useComputerControl";
import styles from "./chat.module.css";

export function AgentPauseNotice({ botId }: { botId: string }) {
  const { paused, control, writable, report, resume, resuming, canResume } = useComputerControl(botId);
  if (!paused) return null;
  return (
    <div className={styles.pauseNotice} aria-label="Agent paused">
      <p role="status">
        <strong>Agent paused.</strong>{" "}
        {control.data?.lease
          ? "Human control is active. Release it in the tab holding control before resuming."
          : writable
            ? "Resume to continue the previous task."
            : report.isPending
              ? "Checking control permissions…"
              : "The bot owner or an operator with execution access can resume it."}
      </p>
      <button type="button" className="primary" disabled={!canResume} onClick={() => resume.mutate()}>
        {resuming ? "Resuming…" : "Resume agent"}
      </button>
      {control.data?.lease ? <Link to={`/bots/${botId}?view=computer&tab=screen`}>Open computer controls</Link> : null}
      {resume.error || control.error || report.error ? (
        <p className="error" role="alert">{(resume.error ?? control.error ?? report.error)?.message}</p>
      ) : null}
    </div>
  );
}
