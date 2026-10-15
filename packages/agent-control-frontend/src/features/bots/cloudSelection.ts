import { api } from "../../api/client";

export type CloudSelection = { provider: string; profile_id: string | null; ownership: string };
export type ComputeConfig = CloudSelection & {
  revision: number; workspace_id: string;
  binding?: { id: string; resource_id: string; generation: number; status: string } | null;
};
export type Profile = { id: string; name: string; provider: string; resources: string[]; allowed_operations: string[]; region: string; default_size: string; storage_policy: string };

export async function applyCloudSelection(botId: string, selection: CloudSelection, current?: ComputeConfig) {
  if (!current) throw new Error("Computer settings are still loading. Try again shortly.");
  if (selection.provider === current.provider && selection.profile_id === current.profile_id && selection.ownership === current.ownership) return current;
  return api<ComputeConfig>(`/api/bots/${botId}/compute-config`, {
    method: "POST", body: JSON.stringify({ provider: selection.provider, profile_id: selection.profile_id, ownership: selection.ownership, request_id: crypto.randomUUID(), expected_revision: current.revision }),
  });
}

