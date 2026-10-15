import { create } from "zustand";
import { latestAutopilot, type AutopilotState } from "./autopilot";

import type { TranscriptMessage } from "../api/client";
import { api } from "../api/client";
import { SessionConnection } from "./sessionConnection";
import {
  applyEvent,
  applySnapshot,
  mergeMessages,
  type ServerMessage,
} from "./v2";
import {
  connectionChanged,
  pendingApprovals,
  emptySession,
  seedHistory,
  type BotSession,
} from "./reduce";
import { resetWorkspaceUi, useWorkspaceUi } from "./workspaceUiStore";

const connections = new Map<string, SessionConnection>();

type SessionStore = {
  removeCapture: (botId: string, captureId: string) => void;
  setAutopilot: (botId: string, mode: AutopilotState) => void;
  sessions: Record<string, BotSession>;
  connect: (botId: string) => void;
  disconnect: (botId: string) => void;
  seed: (botId: string, messages: TranscriptMessage[]) => void;
  sendPrompt: (botId: string, prompt: string, attachmentIds?: string[]) => Promise<boolean>;
  loadEarlier: (botId: string) => Promise<void>;
  decide: (
    botId: string,
    approvalId: string,
    decision: "approve" | "deny",
  ) => void;
  stop: (botId: string) => void;
  closeSandbox: (botId: string) => Promise<boolean>;
};

function sessionOf(
  sessions: Record<string, BotSession>,
  botId: string,
): BotSession {
  return sessions[botId] ?? emptySession();
}

async function command(
  botId: string,
  path: string,
  data: Record<string, unknown>,
): Promise<boolean> {
  const connection = connections.get(botId);
  if (!connection || sessionFor(botId).submitting) return false;
  const patch = (value: Partial<BotSession>) => {
    if (connections.get(botId) !== connection) return;
    useSessionStore.setState((current) => ({
      sessions: {
        ...current.sessions,
        [botId]: { ...sessionOf(current.sessions, botId), ...value },
      },
    }));
  };
  const approvalId = path.match(/^\/approvals\/([^/]+)\/decision$/)?.[1];
  patch({
    submitting: true,
    submittingApprovalId: approvalId,
    commandError: undefined,
  });
  const accepted = await connection.command(`/api/bots/${botId}${path}`, data);
  patch({ submitting: false, submittingApprovalId: undefined });
  return accepted;
}

export const useSessionStore = create<SessionStore>((set) => ({
  sessions: {},
  removeCapture(botId, captureId) {
    set(current => {
      const session = current.sessions[botId];
      return !session ? current : { sessions: { ...current.sessions, [botId]: { ...session, shots: session.shots.filter(shot => shot.id !== captureId) } } };
    });
  },
  setAutopilot(botId, mode) {
    set((current) => {
      const session = sessionOf(current.sessions, botId);
      const autopilot = latestAutopilot(session.autopilot, mode);
      return autopilot === session.autopilot ? current : {
        sessions: { ...current.sessions, [botId]: { ...session, autopilot } },
      };
    });
  },
  connect(botId) {
    if (connections.has(botId)) return;
    set((current) => ({
      sessions: {
        ...current.sessions,
        [botId]: sessionOf(current.sessions, botId),
      },
    }));
    const connection = new SessionConnection(
      botId,
      (status) =>
        set((current) => ({
          sessions: {
            ...current.sessions,
            [botId]: connectionChanged(
              {
                ...sessionOf(current.sessions, botId),
                protocol: 2 as const,
              },
              status,
              Date.now(),
            ),
          },
        })),
      (snapshot) =>
        set((current) => ({
          sessions: {
            ...current.sessions,
            [botId]: applySnapshot(
              sessionOf(current.sessions, botId),
              snapshot,
            ),
          },
        })),
      (event) =>
        set((current) => ({
          sessions: {
            ...current.sessions,
            [botId]: applyEvent(sessionOf(current.sessions, botId), event),
          },
        })),
      (message) =>
        set((current) => ({
          sessions: {
            ...current.sessions,
            [botId]: {
              ...sessionOf(current.sessions, botId),
              commandError: message,
            },
          },
        })),
    );
    connections.set(botId, connection);
    connection.start();
  },
  disconnect(botId) {
    connections.get(botId)?.stop();
    connections.delete(botId);
    useWorkspaceUi.getState().remove(botId);
    set((current) => {
      const sessions = { ...current.sessions };
      delete sessions[botId];
      return { sessions };
    });
  },
  seed(botId, messages) {
    if (sessionFor(botId).protocol === 2) return;
    set((current) => ({
      sessions: {
        ...current.sessions,
        [botId]: seedHistory(sessionOf(current.sessions, botId), messages),
      },
    }));
  },
  async sendPrompt(botId, prompt, attachmentIds) {
    const text = prompt.trim();
    const existing = sessionFor(botId);
    if (
      !text ||
      existing.connection !== "connected" ||
      existing.status === "running" ||
      existing.status === "awaiting" ||
      existing.status === "stopping" ||
      existing.submitting ||
      existing.computerStatus === "failed"
    )
      return false;
    return command(botId, "/runs", { prompt: text, ...(attachmentIds?.length ? { attachment_ids: attachmentIds } : {}) });
  },
  async loadEarlier(botId) {
    const cursor = sessionFor(botId).messagesBefore;
    const connection = connections.get(botId);
    if (!cursor || !connection) return;
    const page = await api<{
      messages: ServerMessage[];
      before: number | null;
    }>(`/api/bots/${botId}/messages?before=${cursor}`);
    if (connections.get(botId) !== connection) return;
    set((current) => ({
      sessions: {
        ...current.sessions,
        [botId]: {
          ...mergeMessages(sessionOf(current.sessions, botId), page.messages),
          messagesBefore: page.before,
        },
      },
    }));
  },
  decide(botId, approvalId, decision) {
    const existing = sessionFor(botId);
    if (
      existing.connection !== "connected" ||
      !pendingApprovals(existing).some((item) => item.approvalId === approvalId)
    )
      return;
    const item = existing.items.find(
      (item) => item.kind === "approval" && item.approvalId === approvalId,
    );
    void command(botId, `/approvals/${approvalId}/decision`, {
      decision,
      revision: item?.kind === "approval" ? (item.revision ?? 1) : 1,
    });
  },
  stop(botId) {
    if (sessionFor(botId).connection !== "connected") return;
    const rid = sessionFor(botId).runId;
    if (rid) void command(botId, `/runs/${rid}/stop`, {});
  },
  async closeSandbox(botId) {
    if (
      sessionFor(botId).connection !== "connected" ||
      !sessionFor(botId).controlBound ||
      sessionFor(botId).status === "closed"
    )
      return false;
    return command(botId, "/computer/close", {
      session_id: sessionFor(botId).sessionId,
    });
  },
}));

export function resetSessions(): void {
  for (const connection of connections.values()) connection.stop();
  connections.clear();
  useSessionStore.setState({ sessions: {} });
  resetWorkspaceUi();
}

export function sessionFor(botId: string): BotSession {
  return sessionOf(useSessionStore.getState().sessions, botId);
}
