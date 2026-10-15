import { useIsMutating, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../../api/client";
import { useHumanControl } from "../../session/humanControl";
import { useSessionStore } from "../../session/store";

export function useComputerControl(botId: string, enabled = true) {
  const client = useQueryClient();
  const report = useQuery({
    queryKey: ["computer", botId],
    enabled,
    queryFn: () => api<{
      computer: { id: string; generation: number; status: string; scope?: string; workspace_id?: string; attached_bot_ids?: string[] } | null;
      workspace_computer?: boolean;
      compatible?: boolean;
      provider?: string;
      display_name?: string;
      power_state?: string;
      connectivity?: string;
      operation?: { operation_id: string; operation: string; status: string; phase: string; detail?: string };
      cloud_details?: { region: string; size: string; ownership: string; storage_policy: string; cleanup_state: string };
      reason?: string;
      local_control?: boolean;
      idle_deadline?: string;
      keep_warm_until?: string;
      retain_until?: string;
      capabilities?: { lifecycle: boolean; remote_control: boolean; desktop_takeover?: boolean; lifecycle_actions?: string[] };
    }>(`/api/bots/${botId}/computer`),
    refetchInterval: (query) => query.state.data?.operation?.status === "accepted" ? 2000 : 10000,
  });
  const computer = report.data?.computer;
  const control = useQuery({
    queryKey: ["control", botId, computer?.id],
    queryFn: () => api<{
      paused: boolean;
      lease: { id: string; status?: string } | null;
      recording?: { state: string; private: number };
    }>(`/api/bots/${botId}/sessions/${computer!.id}/control`),
    enabled: computer?.status === "running",
    refetchInterval: 2000,
  });
  const mutationKey = ["resume-agent", botId, computer?.id];
  const resuming = useIsMutating({ mutationKey }) > 0;
  const resume = useMutation({
    mutationKey,
    mutationFn: () => api(`/api/bots/${botId}/sessions/${computer!.id}/control/resume`, {
      method: "POST",
      body: JSON.stringify({ request_id: crypto.randomUUID() }),
    }),
    onSuccess: () => {
      useHumanControl.setState((state) => ({
        bots: { ...state.bots, [botId]: { ...state.bots[botId], error: undefined } },
      }));
      useSessionStore.setState((state) => {
        const session = state.sessions[botId];
        return session ? {
          sessions: { ...state.sessions, [botId]: { ...session, commandError: undefined } },
        } : state;
      });
    },
    onSettled: () => client.invalidateQueries({ queryKey: ["control", botId] }),
  });
  const writable = report.data?.capabilities?.lifecycle === true;
  const paused = computer?.status === "running" && control.data?.paused === true;
  return {
    report, computer, control, writable, paused, resume, resuming,
    canResume: paused && (writable || report.data?.capabilities?.remote_control === true) && !control.data?.lease && !control.isError && !resuming && (report.data?.provider !== "windows_local" || report.data.local_control === true) && (!report.data?.provider?.startsWith("azure_") || report.data.compatible === true),
  };
}
