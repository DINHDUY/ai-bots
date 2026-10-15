import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../../api/client";
import { useSessionStore } from "../../session/store";
import styles from "./dialog.module.css";

type Policy = {
  id: string;
  operation: string;
  summary: string;
  status: string;
  version: number;
  expires_at: string;
  created_by: string;
};

export function ApprovalPolicies({ botId }: { botId: string }) {
  const autopilot = useSessionStore((s) => s.sessions[botId]?.autopilot?.enabled);
  const client = useQueryClient();
  const policies = useQuery({
    queryKey: ["approval-policies", botId],
    queryFn: () => api<Policy[]>(`/api/bots/${botId}/approval-policies`),
    refetchInterval: 15000,
  });
  const revoke = useMutation({
    mutationFn: (id: string) =>
      api(`/api/bots/${botId}/approval-policies/${id}/revoke`, {
        method: "POST",
        body: JSON.stringify({ request_id: crypto.randomUUID() }),
      }),
    onSuccess: () =>
      client.invalidateQueries({ queryKey: ["approval-policies", botId] }),
  });
  return (
    <details className={styles.approvalRules}>
      <summary>Server approval rules{policies.data ? ` (${policies.data.length})` : ""}</summary>
      <div className={styles.ruleBody}>
        {autopilot ? <p>Autopilot approves all requests while enabled. Saved rules apply again when Autopilot is off.</p> : null}
        <p>
          Rules apply to this bot even when your browser is closed. Create an
          exact rule from an approval card.
        </p>
        {policies.isPending ? <p>Loading rules…</p> : null}
        {policies.error || revoke.error ? (
          <p role="alert">{(policies.error ?? revoke.error)?.message}</p>
        ) : null}
        {policies.data?.length === 0 ? (
          <p>{autopilot ? "No saved rules. Autopilot is on." : "No saved rules. Actions require approval."}</p>
        ) : null}
        <ul>
          {policies.data?.map((policy) => (
            <li key={policy.id}>
              <details className={styles.approvalRule}>
                <summary>
                  {policy.operation} · {policy.status}
                </summary>
                <div className={styles.ruleBody}>
                  <pre style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}>
                    {policy.summary}
                  </pre>
                  <p>
                    Version {policy.version} · Expires{" "}
                    {new Date(policy.expires_at).toLocaleString()}
                  </p>
                  {policy.status === "active" ? (
                    <button
                      type="button"
                      disabled={revoke.isPending}
                      onClick={() => revoke.mutate(policy.id)}
                    >
                      Revoke rule
                    </button>
                  ) : null}
                </div>
              </details>
            </li>
          ))}
        </ul>
      </div>
    </details>
  );
}

export function SaveApprovalPolicy({
  botId,
  approvalId,
  scope,
  disabled,
}: {
  botId: string;
  approvalId: string;
  scope: string;
  disabled?: boolean;
}) {
  const [ttl, setTtl] = useState(86400);
  const [requestId, setRequestId] = useState(() => crypto.randomUUID());
  const [saved, setSaved] = useState(false);
  const client = useQueryClient();
  const create = useMutation({
    mutationFn: () =>
      api(`/api/bots/${botId}/approval-policies`, {
        method: "POST",
        body: JSON.stringify({
          request_id: requestId,
          approval_id: approvalId,
          ttl_seconds: ttl,
        }),
      }),
    onSuccess: () => {
      setSaved(true);
      void client.invalidateQueries({ queryKey: ["approval-policies", botId] });
    },
  });
  return (
    <details>
      <summary>Save an approval rule</summary>
      <p>{scope}</p>
      <p>
        Applies only to this bot, including future runs while your browser is
        closed. Saving does not approve this request. Manage rules in Bot
        settings.
      </p>
      <label>
        Rule duration{" "}
        <select
          value={ttl}
          disabled={saved || create.isPending}
          onChange={(event) => {
            setTtl(Number(event.target.value));
            setRequestId(crypto.randomUUID());
          }}
        >
          <option value={3600}>1 hour</option>
          <option value={86400}>1 day</option>
          <option value={604800}>7 days</option>
        </select>
      </label>
      <button
        type="button"
        disabled={disabled || saved || create.isPending}
        onClick={() => create.mutate()}
      >
        {saved ? "Rule saved" : create.isPending ? "Saving rule…" : "Save rule"}
      </button>
      {create.error ? <p role="alert">{create.error.message}</p> : null}
    </details>
  );
}
