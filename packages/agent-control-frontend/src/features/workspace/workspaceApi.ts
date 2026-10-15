import { api } from "../../api/client";

export type Workspace = { id: string; name: string; role: string };
export type Preferences = {
  revision: number;
  workspace_id: string | null;
  onboarding: string;
  avatar: string;
  display_role: string;
  order: string[];
  folders: Record<string, string>;
  read_cursors: Record<string, number>;
};
export type Group = { id: string; name: string; bot_ids: string[]; revision: number };
export type Routine = {
  id: string;
  version: number;
  enabled: number;
  next_at: string | null;
  definition: Definition;
};
export type Definition = {
  name: string;
  bot_id?: string;
  group_id?: string;
  prompt: string;
  trigger: string;
  timezone: string;
  local_time: string;
  interval_seconds: number;
  missed: string;
  overlap: string;
  enabled: boolean;
  resume_computer: boolean;
  version: number;
  skill_id?: string;
  connection_id?: string;
  connector_operation?: string;
  approval_policy_id?: string;
  parameters?: Record<string, string>;
  timeout_seconds?: number;
  event?: string;
};
export const post = <T,>(path: string, value: unknown, method = "POST") =>
  api<T>(path, { method, body: JSON.stringify(value) });


export type ToolkitData = {
  recordings: { id: string; state: string; private: number; steps: string }[];
  skills: {
    id: string;
    name: string;
    parameters: string;
    installed: boolean;
  }[];
  connections: { id: string; repository: string; status: string }[];
};
