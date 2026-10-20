/* Generated from macos.schema.json; run npm run generate:wire. */

export type Producer = string;
export type TaskId = string;
export type DeviceId = string;
export type TaskDescription = string;
export type Timeout = number;
export type Function =
  | "focus_window"
  | "launch_app"
  | "click"
  | "move"
  | "scroll"
  | "drag"
  | "set_text"
  | "type_text"
  | "key_input"
  | "wait";
export type ObservationId = string;
export type WindowId = string;
export type ControlId = string;
export type ActionId = string;
export type RunId = string;
export type SessionId = string;
export type DeviceId1 = string;
export type ConsoleSession = string;
export type Generation = number;
export type Epoch = string;
export type LocalRevision = number;
export type ExpiresAt = number;
export type Signature = string;
export type Protocol = 1;
export type DeviceId2 = string;
export type Epoch1 = string;
export type ConsoleSession1 = string;
export type Name = string;
export type Revision = number;
export type Sharing = boolean;
export type Armed = boolean;
export type Ready = boolean;
export type ScreenRecording = boolean;
export type Accessibility = boolean;
export type Reason = string;
export type OiRevision = "5a4f706223507fc9d9eb2239cced85385fcb1308";
export type PatchVersion = 1;
export type Scope = "window" | "display";
export type Code = string;
export type Name1 = string;
export type RequestId = string;
export type DeviceId3 = string;
export type ExpectedRevision = number;
export type RequestId1 = string;
export type Generation1 = number;
export type Id = string;
export type Name2 = string;
export type Provider = "macos_local";
export type Revoked = boolean;
export type Online = boolean;
export type Protocol1 = 1;
export type Name3 = string;
export type Revision1 = number;
export type Sharing1 = boolean;
export type Armed1 = boolean;
export type Ready1 = boolean;
export type ScreenRecording1 = boolean;
export type Accessibility1 = boolean;
export type Reason1 = string;
export type OiRevision1 = string;
export type PatchVersion1 = number;
export type Scope1 = "window" | "display";
export type Computers = MacDevice[];
export type TaskId1 = string;
export type State = "running" | "completed" | "failed" | "cancelled" | "outcome_unknown";
export type Text = string;
export type EffectObserved = boolean;
export type Retryable = false;
export type RequestId2 = string;
export type RunId1 = string;

export interface MacContracts {
  assignment: TaskAssignment;
  action: MacAction;
  permit: Permit;
  hello: Hello;
  enrollment: CompleteEnrollment;
  selection: SelectComputer;
  takeover: Takeover;
  devices: MacDeviceList;
  receipt: TaskReceipt;
}
export interface TaskAssignment {
  producer?: Producer;
  task_id: TaskId;
  device_id: DeviceId;
  task_description: TaskDescription;
  task_data?: TaskData;
  timeout?: Timeout;
}
export interface TaskData {
  [k: string]: unknown;
}
export interface MacAction {
  function: Function;
  observation_id: ObservationId;
  window_id: WindowId;
  control_id?: ControlId;
  arguments?: Arguments;
}
export interface Arguments {
  [k: string]: unknown;
}
export interface Permit {
  action_id: ActionId;
  run_id: RunId;
  session_id: SessionId;
  device_id: DeviceId1;
  console_session: ConsoleSession;
  generation: Generation;
  epoch: Epoch;
  local_revision: LocalRevision;
  expires_at: ExpiresAt;
  signature?: Signature;
  action: MacAction;
}
export interface Hello {
  protocol?: Protocol;
  device_id: DeviceId2;
  epoch: Epoch1;
  console_session: ConsoleSession1;
  name: Name;
  revision: Revision;
  sharing?: Sharing;
  armed?: Armed;
  ready?: Ready;
  screen_recording?: ScreenRecording;
  accessibility?: Accessibility;
  reason?: Reason;
  oi_revision?: OiRevision;
  patch_version?: PatchVersion;
  scope?: Scope;
}
export interface CompleteEnrollment {
  code: Code;
  name: Name1;
}
export interface SelectComputer {
  request_id: RequestId;
  device_id: DeviceId3;
  expected_revision: ExpectedRevision;
}
export interface Takeover {
  request_id: RequestId1;
  generation: Generation1;
}
export interface MacDeviceList {
  computers: Computers;
}
export interface MacDevice {
  id: Id;
  name: Name2;
  provider: Provider;
  revoked: Revoked;
  online: Online;
  state: PublicMacState | null;
}
export interface PublicMacState {
  protocol: Protocol1;
  name: Name3;
  revision: Revision1;
  sharing: Sharing1;
  armed: Armed1;
  ready: Ready1;
  screen_recording: ScreenRecording1;
  accessibility: Accessibility1;
  reason: Reason1;
  oi_revision: OiRevision1;
  patch_version: PatchVersion1;
  scope: Scope1;
}
export interface TaskReceipt {
  task_id: TaskId1;
  state: State;
  text?: Text;
  effect_observed?: EffectObserved;
  retryable?: Retryable;
  request_id: RequestId2;
  run_id: RunId1;
}
