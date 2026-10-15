import { useId } from "react";
import { useIsMutating, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, ApiError } from "../../api/client";
import type { AutopilotState } from "../../session/autopilot";
import { useSessionStore } from "../../session/store";
import styles from "./autopilot.module.css";

type Response = AutopilotState & { can_manage: boolean };

export function AutopilotToggle({
  botId,
  showUnavailable = false,
}: {
  botId: string;
  showUnavailable?: boolean;
}) {
  const descriptionId = useId();
  const client = useQueryClient();
  const key = ["autopilot", botId];
  const mode = useSessionStore((s) => s.sessions[botId]?.autopilot);
  const capabilities = useQuery({
    queryKey: ["capabilities"],
    queryFn: () => api<{ autopilot?: boolean }>("/api/capabilities"),
    staleTime: 60_000,
    refetchInterval: (query) => showUnavailable && query.state.data?.autopilot !== true ? 10_000 : false,
  });
  const setting = useQuery({
    queryKey: key,
    enabled: capabilities.data?.autopilot === true,
    queryFn: async ({ signal }) => {
      const response = await api<Response>(`/api/bots/${botId}/autopilot`, { signal });
      if (!signal.aborted) useSessionStore.getState().setAutopilot(botId, response);
      return response;
    },
  });
  const saving = useIsMutating({ mutationKey: key }) > 0;
  const change = useMutation({
    mutationKey: key,
    mutationFn: (body: { request_id: string; enabled: boolean; expected_revision: number }) =>
      api<Response>(`/api/bots/${botId}/autopilot`, { method: "POST", body: JSON.stringify(body) }),
    // A lost response retries the same command receipt, never a new decision.
    retry: (count, error) => count < 1 && (!(error instanceof ApiError) || error.status >= 500),
    onSuccess: (response) => {
      // A cleared cache means the user signed out or this bot was removed.
      if (!client.getQueryState(key)) return;
      useSessionStore.getState().setAutopilot(botId, response);
      client.setQueryData<Response>(key, (current) => current && current.revision > response.revision ? current : response);
    },
    onSettled: () => { void client.invalidateQueries({ queryKey: key }); },
  });
  if (capabilities.data?.autopilot !== true) {
    if (!showUnavailable) return null;
    return (
      <div className={styles.setting} data-autopilot-toggle>
        <label className={styles.label}>
          <input type="checkbox" checked={false} disabled aria-describedby={descriptionId} />
          <span>Autopilot</span>
        </label>
        <p id={descriptionId} role={capabilities.isError ? "alert" : "status"}>
          {capabilities.isPending ? "Checking Autopilot availability…"
            : capabilities.isError ? `Could not load Autopilot: ${capabilities.error.message}`
              : "Backend update required. Restart the updated control backend to enable Autopilot."}
        </p>
        {capabilities.isError ? <button type="button" onClick={() => void capabilities.refetch()}>Retry Autopilot</button> : null}
      </div>
    );
  }
  return (
    <div className={styles.setting} data-autopilot-toggle>
      <label className={styles.label}>
        <input type="checkbox" checked={mode?.enabled ?? false}
          disabled={!setting.data?.can_manage || !mode || setting.isError || saving}
          aria-describedby={descriptionId}
          onChange={(event) => {
            if (mode) change.mutate({ request_id: crypto.randomUUID(), enabled: event.target.checked, expected_revision: mode.revision });
          }} />
        <span>Autopilot</span>
        {saving ? <span className={styles.saving} role="status">Saving…</span> : null}
      </label>
      <p id={descriptionId}>Automatically approve all requests for this bot, including scheduled runs and handoffs. Applies immediately to pending requests.</p>
      {setting.data && !setting.data.can_manage ? <p>Only the bot owner can change Autopilot.</p> : null}
      {change.error || setting.error ? <p role="alert">{(change.error ?? setting.error)?.message}</p> : null}
      {setting.isError ? <button type="button" onClick={() => void setting.refetch()}>Reload Autopilot</button> : null}
    </div>
  );
}

export function AutopilotBadge({ enabled }: { enabled?: boolean }) {
  return enabled ? <span className={styles.badge}>Autopilot on</span> : null;
}
