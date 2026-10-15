export type LogType = "THOUGHT" | "TOOL_CALL" | "RESULT" | "ERROR" | "SYSTEM" | "SCREENSHOT_CAPTURE";

export type InboundFrame =
  | { event: "session"; session_id: string }
  | { event: "log"; source?: string; type: LogType | string; payload: string }
  | { event: "artifact_written"; source?: string; meta: { path: string; preview: string } }
  | { event: "approval_required"; source?: string; approval_id: string; action: string; detail: string }
  | { event: "done"; session_id?: string }
  | { event: "error"; payload: string; session_id?: string }
  | { event: "closed"; session_id?: string };

export type OutboundFrame =
  | { action: "start"; bot_id: string; prompt: string }
  | { action: "approve"; approval_id: string; decision: "approve" | "deny" }
  | { action: "stop" }
  | { action: "close" };
