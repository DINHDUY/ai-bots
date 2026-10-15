export type AutopilotState = {
  bot_id: string;
  enabled: boolean;
  revision: number;
  changed_by: string | null;
  changed_at: string | null;
};

// HTTP receipts, snapshots and the event stream can arrive in any order.
export function latestAutopilot(
  current: AutopilotState | undefined,
  incoming: AutopilotState | undefined,
): AutopilotState | undefined {
  return incoming && (!current || incoming.revision > current.revision)
    ? incoming
    : current;
}
