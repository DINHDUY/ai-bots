import type { ChatItem } from "../../session/reduce";
import { Icon } from "../../components/ui/Icon";
import styles from "./chat.module.css";
import { SaveApprovalPolicy } from "../bots/ApprovalPolicies";
type Props = {
  item: Extract<ChatItem, { kind: "approval" }>;
  onAllow: () => void;
  onDeny: () => void;
  disabled?: boolean;
  submitting?: boolean;
  botId?: string;
};
export function ApprovalCard({
  item,
  onAllow,
  onDeny,
  disabled,
  submitting,
  botId,
}: Props) {
  const answered = Boolean(item.decision) || item.stale;
  return (
    <article
      className={styles.approval}
      aria-label={`Approval for ${item.action}`}
    >
      <div className={styles.approvalContent}>
        <div className={styles.approvalTitle}>
          <Icon name="shield" />
          <strong>
            {submitting
              ? "Submitting decision…"
              : item.actionStatus
                ? item.actionStatus === "executing"
                  ? "Executing action"
                  : "Action result"
                : item.decision
                  ? item.acknowledged
                    ? "Decision accepted"
                    : "Decision sent"
                  : item.stale
                    ? "Approval no longer active"
                    : "Approval required"}
          </strong>
          <span className="spacer" />
          <span className="badge">{item.action}</span>
        </div>
        <pre className={styles.approvalDetail}>{item.detail}</pre>
        {item.decisionSource === "autopilot" ? (
          <div className={styles.approvalHint}>
            <strong>Auto-approved by Autopilot</strong>
            <details><summary>Authorization details</summary>
              Owner: {item.decidedBy} · Autopilot revision {item.autopilotRevision}
            </details>
            {item.decisionReason ? <p>{item.decisionReason}. Request fresh approval to continue.</p> : null}
          </div>
        ) : null}
        {item.resultText ? (
          <p className={styles.decision} role="status">
            {item.resultText}
          </p>
        ) : item.decision ? (
          <p className={styles.decision}>
            Decision: {item.decision === "approve" ? "Allowed" : "Denied"}{" "}
            <span>
              {item.decision === "deny"
                ? "· This action will not execute."
                : item.acknowledged
                  ? "· Accepted by the server; execution outcome will follow."
                  : "· Local choice; check the subsequent result."}
            </span>
          </p>
        ) : item.stale ? (
          <p className={styles.decision}>
            The turn ended or its connection was interrupted. This request
            cannot be answered.
          </p>
        ) : (
          <p className={styles.approvalHint}>
            Review the action before your bot continues.
          </p>
        )}
      </div>
      {botId && item.policyScope && !item.stale && item.decision !== "deny" ? (
        <SaveApprovalPolicy
          botId={botId}
          approvalId={item.approvalId}
          scope={item.policyScope}
          disabled={disabled || submitting}
        />
      ) : null}
      {!answered && item.expiresAt ? (
        <p className={styles.approvalHint}>
          Expires {new Date(item.expiresAt).toLocaleTimeString()}
        </p>
      ) : null}
      {!answered ? (
        <div className={styles.approvalActions}>
          <span className="spacer" />
          <button type="button" disabled={disabled} onClick={onDeny}>
            Deny
          </button>
          <button
            type="button"
            className="primary"
            disabled={disabled}
            onClick={onAllow}
          >
            <Icon name="check" />
            Allow once
          </button>
        </div>
      ) : null}
    </article>
  );
}
