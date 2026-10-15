import { create } from "zustand";
export type BotViewState = {
  draft: string;
  shotId: string | null;
  filePath: string | null;
  zoom: boolean;
  transcriptTop?: number;
  terminalTop?: number;
  transcriptFollow: boolean;
  terminalFollow: boolean;
};
export const emptyView: BotViewState = {
  draft: "",
  shotId: null,
  filePath: null,
  zoom: false,
  transcriptFollow: true,
  terminalFollow: true,
};
type UIState = {
  bots: Record<string, BotViewState>;
  patch: (botId: string, patch: Partial<BotViewState>) => void;
  remove: (botId: string) => void;
};
export const useWorkspaceUi = create<UIState>((set) => ({
  bots: {},
  patch: (id, patch) =>
    set((state) => ({
      bots: {
        ...state.bots,
        [id]: { ...emptyView, ...state.bots[id], ...patch },
      },
    })),
  remove: (id) =>
    set((state) => {
      const bots = { ...state.bots };
      delete bots[id];
      return { bots };
    }),
}));
export function resetWorkspaceUi() {
  useWorkspaceUi.setState({ bots: {} });
}
export function readPreference(key: string, fallback = ""): string {
  try {
    return localStorage.getItem(`agent-control:${key}`) ?? fallback;
  } catch {
    return fallback;
  }
}
export function savePreference(key: string, value: string) {
  try {
    localStorage.setItem(`agent-control:${key}`, value);
  } catch {
    /* Storage can be disabled. */
  }
}
