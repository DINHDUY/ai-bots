import { useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../../api/client";
import {
  takeControl,
  releaseControl,
  useHumanControl,
  leaseBody,
} from "../../session/humanControl";
import { Dialog } from "../../components/ui/Dialog";
import styles from "./workspace.module.css";
import { AutopilotToggle } from "../bots/AutopilotToggle";
import { useComputerControl } from "./useComputerControl";

export function ComputerControls({ botId }: { botId: string }) {
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [confirm, setConfirm] = useState("");
  const [surface, setSurface] = useState<"browser" | "desktop">("browser");
  const local = useHumanControl((s) => s.bots[botId]);
  const { report, computer, control, writable, paused, resume, resuming, canResume } = useComputerControl(botId);
  const windows = report.data?.provider === "windows_local";
  const cloud = report.data?.provider?.startsWith("azure_");
  const cloudActions = report.data?.capabilities?.lifecycle_actions ?? [];
  const shared = report.data?.workspace_computer === true;
  const operation = report.data?.operation;
  const cloudLabels: Record<string, string> = { start: "Start computer", stop: "Stop computer", create: "Create managed computer", close: "Detach computer", reset: "Reset sandbox", "delete-managed": "Delete managed computer", "keep-warm": "Keep warm 30m" };
  const cloudButtonLabels: Record<string, string> = { start: "Start", stop: "Stop", create: "Create", close: "Detach", reset: "Reset", "delete-managed": "Delete", "keep-warm": "+30m" };
  async function action(operation: string) {
    setBusy(true);
    setError("");
    try {
      const result = await api<{ status: string; detail?: string }>(
        `/api/bots/${botId}/lifecycle/${operation}`,
        {
          method: "POST",
          body: JSON.stringify({
            request_id: crypto.randomUUID(),
            generation: computer?.generation ?? 0,
            minutes: 30,
          }),
        },
      );
      if (result.status !== "completed" && result.status !== "accepted")
        throw new Error(result.detail ?? result.status);
      await report.refetch();
      await control.refetch();
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
      setConfirm("");
    }
  }
  return (
    <div className={styles.computerControls} aria-label="Computer controls">
      <AutopilotToggle botId={botId} />
      {cloud ? <div className={styles.controlMessage}>
        <p role="status">{report.data?.display_name} · Power: {report.data?.power_state} · {report.data?.connectivity?.replaceAll("_", " ")}</p>
        {operation ? <p role={operation.status === "failed" || operation.status === "outcome_unknown" ? "alert" : "status"}>{operation.operation}: {operation.phase.replaceAll("_", " ")}. {operation.detail}</p> : null}
        {report.data?.cloud_details ? <details><summary>Computer details</summary><p>{report.data.cloud_details.region} · {report.data.cloud_details.size} · {report.data.cloud_details.ownership} · {report.data.cloud_details.storage_policy.replaceAll("_", " ")}</p><p>Cleanup: {report.data.cloud_details.cleanup_state}. Retained disks may continue to incur charges after stopping.</p></details> : null}
      </div> : null}
      {windows ? <p className={styles.controlMessage} role="status">{report.data?.reason || "Pair and enable the Windows companion in Bot settings."}{paused ? " Restore Allow agent control locally, then Resume agent." : ""}</p> : null}
      <div className={styles.controlDetails}>
        {control.data?.recording ? (
          <span role="status">
            Teach a task:{" "}
            {control.data.recording.private
              ? "Private input — captures omitted"
              : control.data.recording.state}
          </span>
        ) : null}
        {report.data?.idle_deadline && computer?.status === "running" ? (
          <span title="Health checks and viewers do not extend this deadline">
            {windows ? "Idle disconnect:" : "Idle close:"}{" "}
            {new Date(
              report.data.keep_warm_until &&
                report.data.keep_warm_until > report.data.idle_deadline
                ? report.data.keep_warm_until
                : report.data.idle_deadline,
            ).toLocaleTimeString()}
          </span>
        ) : null}
        {computer?.status === "hibernated" && report.data?.retain_until ? (
          <span>
            Retained until {new Date(report.data.retain_until).toLocaleString()}
          </span>
        ) : null}
        {local?.lease ? (
          <span role="status">Human control · agent paused</span>
        ) : null}
      </div>
      <div className={styles.controlActions} role="group" aria-label="Computer actions" tabIndex={0}>
        {windows && computer?.status === "running" && report.data?.capabilities?.desktop_takeover ? <button type="button" aria-label="Take control on this PC" title="Take control on this PC" disabled={busy} onClick={async () => {
          setBusy(true); setError("");
          try { await api(`/api/bots/${botId}/computer/takeover`, { method: "POST", body: JSON.stringify({ request_id: crypto.randomUUID(), generation: computer.generation }) }); await control.refetch(); await report.refetch(); }
          catch (e) { setError(String(e)); } finally { setBusy(false); }
        }}>Control PC</button> : null}
        {paused ? (
          <button
            type="button"
            className="primary"
            aria-label={resuming ? "Resuming agent" : "Resume agent"}
            disabled={busy || !canResume}
            title={control.data?.lease ? "Release human control before resuming" : "Continue the previous task"}
            onClick={() => resume.mutate()}
          >
            {resuming ? "Resuming…" : "Resume"}
          </button>
        ) : null}
        {computer?.status === "running" &&
        report.data?.capabilities?.remote_control ? (
          <>
            <select
              aria-label="Control surface"
              title="Control surface"
              value={surface}
              disabled={!!local?.lease}
              onChange={(e) => setSurface(e.target.value as typeof surface)}
            >
              <option value="browser">Browser</option>
              <option value="desktop">Desktop</option>
            </select>
            <button
              disabled={busy}
              aria-label={local?.lease ? "Release control" : "Take control"}
              title={local?.lease ? "Release human control" : "Take control of the selected surface"}
              onClick={async () => {
                setBusy(true);
                try {
                  if (local?.lease) await releaseControl(botId);
                  else
                    await takeControl(
                      botId,
                      computer.id,
                      computer.generation,
                      surface,
                    );
                  setError("");
                } catch (e) {
                  setError(String(e));
                } finally {
                  setBusy(false);
                  void control.refetch();
                }
              }}
            >
              {local?.lease ? "Release" : "Control"}
            </button>
            {!cloud && !shared ? <><button title="Hibernate computer" disabled={busy} onClick={() => setConfirm("hibernate")}>
              Hibernate
            </button>
            <button aria-label="Keep warm 30m" title="Keep computer warm for 30 minutes" disabled={busy} onClick={() => void action("keep-warm")}>
              +30m
            </button>
            <button title="Reset computer" disabled={busy} onClick={() => setConfirm("reset")}>
              Reset
            </button></> : null}
          </>
        ) : !shared && !cloud && writable && computer?.status === "hibernated" ? (
          <button aria-label="Resume computer" title="Resume computer" disabled={busy} onClick={() => void action("resume")}>
            Wake
          </button>
        ) : !shared && !cloud && writable && (!computer || computer.status === "closed") ? (
          <button aria-label={windows ? "Connect Windows PC" : "Create computer"} title={windows ? "Connect Windows PC" : "Create computer"} disabled={busy} onClick={() => void action("create")}>
            {windows ? "Connect PC" : "Create"}
          </button>
        ) : null}
        {!shared && cloud ? cloudActions.map(item => <button key={item} type="button" aria-label={cloudLabels[item] ?? item} title={cloudLabels[item] ?? item} disabled={busy || operation?.status === "accepted"} onClick={() => ["stop", "reset", "close", "delete-managed", "create"].includes(item) ? setConfirm(item) : void action(item)}>{cloudButtonLabels[item] ?? item}</button>) : null}
        {shared ? <Link to={`/workspace?tab=computer&workspace=${report.data?.computer?.workspace_id ?? ""}`}>Workspace computer settings</Link> : null}
        {control.data?.recording && local?.lease ? (
          <button
            onClick={async () => {
              try {
                await api(
                  `/api/bots/${botId}/sessions/${local.lease!.session_id}/recordings`,
                  {
                    method: "POST",
                    body: JSON.stringify({
                      ...leaseBody(local.lease!),
                      operation: control.data?.recording?.private
                        ? "public"
                        : "private",
                    }),
                  },
                );
                void control.refetch();
              } catch (e) {
                setError(String(e));
              }
            }}
          >
            {control.data.recording.private ? "Record input" : "Private input"}
          </button>
        ) : null}
      </div>
      {paused && control.data?.lease && !local?.lease ? (
        <p className={styles.controlMessage}>Human control is active in another tab. Release it there before resuming.</p>
      ) : null}
      {resume.error || control.error ? (
        <p className={styles.controlMessage} role="alert">{(resume.error ?? control.error)?.message}</p>
      ) : null}
      {error || local?.error ? (
        <p className={styles.controlMessage} role="alert">
          {error || local?.error}
        </p>
      ) : null}
      <Dialog
        open={!!confirm}
        title={cloud ? `${cloudLabels[confirm] ?? confirm}?` : `${confirm === "reset" ? "Reset" : "Hibernate"} computer?`}
        onClose={() => setConfirm("")}
      >
        <p>
          {cloud ? confirm === "delete-managed" ? "Delete this recorded managed compute resource? This cannot be undone. Retained VM disks and network resources remain in cleanup inventory. Export required files first."
            : confirm === "create" ? "Provision the approved machine size and image? Azure compute and storage charges apply."
            : confirm === "reset" ? "Stop work and create a new sandbox generation? The old workspace directory, conversation, and artifacts are retained."
            : confirm === "close" ? "Retire this bot's sandbox and revoke its host connection? Your Azure host and workspace data remain tracked. Managed host cleanup may continue in the background."
            : "Stop tasks and terminals, then stop Azure compute? Workspace files and disks remain. Starting the computer will not automatically resume the agent."
            : confirm === "reset"
            ? "This removes all live workspace files and provisions a new generation. Retained artifacts and conversation remain."
            : "This stops running tasks and terminals. Workspace files remain for up to seven days. Browser and process state will be lost."}
        </p>
        <button onClick={() => setConfirm("")}>Cancel</button>
        <button disabled={busy} onClick={() => void action(confirm)}>
          Confirm {confirm}
        </button>
      </Dialog>
    </div>
  );
}
