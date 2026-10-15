import type { ToolSelection } from "../../api/client";

export const messagingTool: ToolSelection = {
  library_id: "workspace.messaging",
  tool_id: "workspace_messaging",
  version: "1.0.0",
  configuration: {},
};
export type Collaboration = {
  bot_id: string;
  workspace_id: string;
  name: string;
  purpose: string;
  state: string;
  revision: number;
  expires_at: string | null;
  published: number;
};
export type CollaborationDraft = {
  revision: number;
  enabled: boolean;
  purpose: string;
  expires_at: string | null;
};
export type Peer = Collaboration & {
  enrollment_id: string;
  capabilities: string[];
  availability: string;
  computer: string;
};
export type ChannelMessage = {
  id: string;
  thread_id: string;
  seq: number;
  kind: string;
  sender_name: string;
  sender_bot_id: string | null;
  recipient_id: string | null;
  reply_to: string | null;
  body: string;
  created_at: string;
  artifacts?: {
    id: string;
    blob_id: string;
    revision: string;
    revoked: number;
  }[];
};
export type Delivery = {
  id: string;
  thread_id: string;
  message_id: string | null;
  target_bot_id: string;
  state: string;
  reason: string | null;
  run_id: string | null;
  mode: string;
};
export type ChannelSnapshot = {
  workspace_id: string;
  enabled: number;
  revision: number;
  seq: number;
  role: string;
  enroll_future: boolean;
  owned_bots: Collaboration[];
  directory: { bots: Peer[]; revision: number; next_offset: number | null };
  messages: ChannelMessage[];
  next_before: number | null;
  deliveries: Delivery[];
  threads: {
    id: string;
    state: string;
    principal_id: string;
    runs_used: number;
    run_limit?: number;
    deadline: string;
  }[];
};
export const channelState = (value: string) =>
  ({
    enabled: "On",
    disabled: "Collaboration off",
    ready: "Ready",
    busy: "Busy",
    queued: "Queued",
    blocked: "Waiting",
    admitted: "Running",
    completed: "Run completed",
    expired: "Expired",
    removed: "Removed",
    leaving: "Leaving",
    waiting_peer: "Waiting for reply",
    cancelled: "Cancelled",
    failed: "Failed",
    open: "Open",
    resolved: "Resolved",
    budget_exhausted: "Budget exhausted",
  })[value] ?? value.replaceAll("_", " ");
