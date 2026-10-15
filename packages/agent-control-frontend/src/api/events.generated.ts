/* Generated from events.schema.json; run npm run generate:wire. */

export type WireFrame = EventEnvelope | (SnapshotFrame | ReadyFrame);
export type ActionId = string | null;
export type BotId = string;
export type JsonValue = unknown;
export type EventId = string;
export type Generation = number | null;
export type OccurredAt = string;
export type RunId = string | null;
export type SchemaVersion = 2;
export type Seq = number;
export type SessionId = string | null;
export type Type = string;
export type WorkspaceId = string | null;
export type BotId1 = string;
export type Computer = {
  [k: string]: JsonValue;
} | null;
export type Events = EventEnvelope[];
export type Content = string;
export type Id = string;
export type OccurredAt1 = string | null;
export type Ordinal = number;
export type Role = "user" | "assistant";
export type Seq1 = number;
export type Messages = Message[];
export type MessagesBefore = number | null;
export type ObservationsTruncated = boolean;
export type PendingApprovals = {
  [k: string]: JsonValue;
}[];
export type Run = {
  [k: string]: JsonValue;
} | null;
export type SchemaVersion1 = 2;
export type SnapshotSeq = number;
export type Type1 = "snapshot";
export type Seq2 = number;
export type Type2 = "ready";

export interface EventEnvelope {
  action_id?: ActionId;
  bot_id: BotId;
  data: Data;
  event_id: EventId;
  generation?: Generation;
  occurred_at: OccurredAt;
  run_id: RunId;
  schema_version: SchemaVersion;
  seq: Seq;
  session_id: SessionId;
  type: Type;
  workspace_id?: WorkspaceId;
}
export interface Data {
  [k: string]: JsonValue;
}
export interface SnapshotFrame {
  data: SnapshotData;
  type: Type1;
}
export interface SnapshotData {
  bot_id: BotId1;
  computer: Computer;
  events: Events;
  messages: Messages;
  messages_before: MessagesBefore;
  observations_truncated: ObservationsTruncated;
  pending_approvals: PendingApprovals;
  run: Run;
  schema_version: SchemaVersion1;
  snapshot_seq: SnapshotSeq;
  [k: string]: unknown;
}
export interface Message {
  content: Content;
  id: Id;
  occurred_at: OccurredAt1;
  ordinal: Ordinal;
  role: Role;
  seq: Seq1;
  [k: string]: unknown;
}
export interface ReadyFrame {
  seq: Seq2;
  type: Type2;
}
