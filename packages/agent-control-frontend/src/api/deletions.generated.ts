/* Generated from deletions.schema.json; run npm run generate:wire. */

export type RequestId = string;
export type PreviewDigest = string;
export type ConfirmName = string;
export type WorkspaceId = string;
export type WorkspaceName = string;
export type Id = string;
export type Name = string;
export type Bots = BotSummary[];
export type Code = string;
export type Message = string;
export type Url = string;
export type Blockers = Blocker[];
export type BindingId = string;
export type Provider = string;
export type ResourceId = string;
export type CleanupState = string;
export type Url1 = string;
export type Retained = RetainedComputer[];
export type PreviewDigest1 = string;
export type RequestId1 = string;
export type WorkspaceId1 = string;
export type WorkspaceName1 = string;
export type DeletedAt = string;
export type Retained1 = RetainedComputer[];
export type State = "pending" | "needs_attention" | "complete";
export type Remaining = number;
export type BytesRemaining = number;
export type Errors = string[];
export type Items = DeletionResult[];
export type NextCursor = number | null;

export interface DeletionContracts {
  command: DeleteCommand;
  preview: DeletionPreview;
  result: DeletionResult;
  history: DeletionHistory;
}
export interface DeleteCommand {
  request_id: RequestId;
  preview_digest: PreviewDigest;
  confirm_name: ConfirmName;
}
export interface DeletionPreview {
  workspace_id: WorkspaceId;
  workspace_name: WorkspaceName;
  bots: Bots;
  counts: Counts;
  blockers: Blockers;
  retained: Retained;
  preview_digest: PreviewDigest1;
}
export interface BotSummary {
  id: Id;
  name: Name;
}
export interface Counts {
  [k: string]: number;
}
export interface Blocker {
  code: Code;
  message: Message;
  url: Url;
}
export interface RetainedComputer {
  binding_id: BindingId;
  provider: Provider;
  resource_id: ResourceId;
  cleanup_state: CleanupState;
  url: Url1;
}
export interface DeletionResult {
  request_id: RequestId1;
  workspace_id: WorkspaceId1;
  workspace_name: WorkspaceName1;
  deleted_at: DeletedAt;
  counts: Counts1;
  retained: Retained1;
  cleanup: CleanupStatus;
}
export interface Counts1 {
  [k: string]: number;
}
export interface CleanupStatus {
  state: State;
  remaining: Remaining;
  bytes_remaining: BytesRemaining;
  errors: Errors;
}
export interface DeletionHistory {
  items: Items;
  next_cursor?: NextCursor;
}
