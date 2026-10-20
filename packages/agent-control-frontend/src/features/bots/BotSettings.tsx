import { useEffect, useState } from "react";
import type { FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";

import {
  api,
  providersFor,
  type Bot,
  type BotDetail,
  type Credential,
  type ToolSelection,
  type ToolState,
} from "../../api/client";
import { useSessionStore } from "../../session/store";
import styles from "./dialog.module.css";
import { ApprovalPolicies } from "./ApprovalPolicies";
import { AutopilotToggle } from "./AutopilotToggle";
import { MacComputerSettings } from "./MacComputerSettings";
import { WindowsComputerSettings } from "./WindowsComputerSettings";
import { CloudComputerSettings } from "./CloudComputerSettings";
import { applyCloudSelection, type CloudSelection, type ComputeConfig } from "./cloudSelection";

import { ToolLibraryPicker } from "./ToolLibraryPicker";
import { CollaborationFields } from "./CollaborationFields";
import { messagingTool, type Collaboration, type CollaborationDraft } from "../workspace/channel";

export function BotSettings({ bot, onSaved }: { bot: Bot; onSaved?: () => void }) {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const disconnect = useSessionStore((state) => state.disconnect);
  const session = useSessionStore((state) => state.sessions[bot.id]);
  const capabilities = useQuery({ queryKey: ["capabilities"], queryFn: () => api<{ tool_libraries?: boolean; workspace_bot_channels?: boolean }>("/api/capabilities") });
  const collaboration = useQuery({ queryKey: ["bot-collaboration", bot.id], queryFn: () => api<Collaboration>(`/api/bots/${bot.id}/collaboration`), enabled: !!capabilities.data?.workspace_bot_channels });
  const [collaborationDraft, setCollaborationDraft] = useState<CollaborationDraft | null>(null);
  const toolsEnabled = !!capabilities.data?.tool_libraries;
  const toolsQuery = useQuery({ queryKey: ["bot-tools", bot.id], queryFn: () => api<ToolState>(`/api/bots/${bot.id}/tools`), enabled: toolsEnabled });
  const [toolDraft, setToolDraft] = useState<{ selection: ToolSelection[]; revision: number } | null>(null);
  useEffect(() => {
    if (toolsEnabled && session?.toolsRevision !== undefined) void queryClient.invalidateQueries({ queryKey: ["bot-tools", bot.id] });
  }, [session?.toolsRevision, toolsEnabled, queryClient, bot.id]);
  const toolValue = toolDraft?.selection ?? toolsQuery.data?.tool_selection ?? [];
  const changeTools = (selection: ToolSelection[]) => setToolDraft({ selection, revision: toolDraft?.revision ?? toolsQuery.data!.tools_revision });
  const [error, setError] = useState("");
  const [instructions, setInstructions] = useState(bot.instructions);
  const [windowsBusy, setWindowsBusy] = useState(false);
  const [cloudBusy, setCloudBusy] = useState(false);
  const [cloudSelection, setCloudSelection] = useState<CloudSelection | null>(null);
  const credentials = useQuery({
    queryKey: ["credentials"],
    queryFn: () => api<Credential[]>("/api/credentials"),
  });
  useEffect(() => {
    setInstructions(bot.instructions);
  }, [bot.id, bot.updated_at, bot.instructions]);

  const allowed = providersFor(bot.framework) ?? [];
  const matching = (credentials.data ?? []).filter((item) =>
    allowed.includes(item.provider),
  );

  const save = useMutation({
    mutationFn: async ({ deviceId, ...body }: {
      name: string;
      instructions: string;
      default_prompt: string;
      credential_id: string;
      model: string;
      deviceId: string;
      tool_selection?: ToolSelection[];
      expected_tools_revision?: number;
      collaboration?: CollaborationDraft;
    }) => {
      if (deviceId && !["ufo", "open_interface"].includes(bot.framework)) {
        throw new Error("This bot cannot use a Windows PC. Choose Create Windows bot to create a Microsoft UFO · Windows desktop bot.");
      }
      const configKey = ["compute-config", bot.id];
      const config = queryClient.getQueryData<{ device_id: string | null; revision: number }>(configKey);
      if (deviceId && !config) {
        throw new Error("Computer settings are not loaded. Retry loading them before saving.");
      }
      const updated = await api<Bot>(`/api/bots/${bot.id}`, {
        method: "PATCH",
        body: JSON.stringify(body),
      });
      if (updated.tools_revision !== undefined && updated.tool_selection) {
        const selection = updated.tool_selection, revision = updated.tools_revision;
        setToolDraft({ selection, revision });
        queryClient.setQueryData<ToolState>(["bot-tools", bot.id], current => current ? { ...current, tool_selection: selection, tools_revision: revision } : current);
        void queryClient.invalidateQueries({ queryKey: ["bot-tools", bot.id] });
      }
      if (deviceId && deviceId !== config?.device_id) {
        try {
          const assigned = await api<{ device_id: string; revision: number }>(
            `/api/bots/${bot.id}/compute-config`, {
              method: "POST",
              body: JSON.stringify({
                request_id: crypto.randomUUID(), device_id: deviceId,
                expected_revision: config!.revision,
              }),
            },
          );
          queryClient.setQueryData(configKey, assigned);
          void queryClient.invalidateQueries({ queryKey: ["computer", bot.id] });
        } catch (caught) {
          void queryClient.invalidateQueries({ queryKey: configKey });
          void queryClient.invalidateQueries({ queryKey: ["bots"] });
          throw new Error(`Bot details saved, but the ${bot.framework === "open_interface" ? "Mac" : "Windows PC"} was not assigned: ${caught instanceof Error ? caught.message : "Request failed"}`);
        }
      }
      if (cloudSelection && !["ufo", "open_interface"].includes(bot.framework)) {
        try {
          const selected = await applyCloudSelection(bot.id, cloudSelection, queryClient.getQueryData<ComputeConfig>(configKey));
          queryClient.setQueryData(configKey, selected);
          setCloudSelection(null);
          void queryClient.invalidateQueries({ queryKey: ["computer", bot.id] });
        } catch (caught) {
          throw new Error(`Bot details saved, but computer selection failed: ${caught instanceof Error ? caught.message : "Request failed"}`);
        }
      }
      return updated;
    },
    onSuccess: (updated) => {
      queryClient.setQueryData<BotDetail>(["bot", bot.id], (current) =>
        current ? { ...current, ...updated } : undefined,
      );
      queryClient.setQueryData<Bot[]>(["bots"], (current) =>
        current?.map((item) =>
          item.id === updated.id ? { ...item, ...updated } : item,
        ),
      );
      void queryClient.invalidateQueries({ queryKey: ["bots"] });
      void queryClient.invalidateQueries({ queryKey: ["bot", bot.id] });
      setToolDraft(null);
      setCollaborationDraft(null);
      void queryClient.invalidateQueries({ queryKey: ["bot-collaboration", bot.id] });
      void queryClient.invalidateQueries({ queryKey: ["channel"] });
      void queryClient.invalidateQueries({ queryKey: ["bot-tools", bot.id] });
      onSaved?.();
    },
  });

  const remove = useMutation({
    mutationFn: () =>
      api<{ status: string }>(`/api/bots/${bot.id}`, { method: "DELETE" }),
    onSuccess: async () => {
      disconnect(bot.id);
      await queryClient.invalidateQueries({ queryKey: ["bots"] });
      navigate("/overview");
    },
  });

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (save.isPending || windowsBusy || cloudBusy) return;
    setError("");
    const data = new FormData(event.currentTarget);
    if (!data.get("credential_id")) {
      setError("Choose an API key before saving.");
      return;
    }
    try {
      await save.mutateAsync({
        name: String(data.get("name") ?? ""),
        instructions,
        default_prompt: String(data.get("default_prompt") ?? "").trim(),
        credential_id: String(data.get("credential_id") ?? ""),
        model: String(data.get("model") ?? ""),
        deviceId: String(data.get(bot.framework === "open_interface" ? "macos_device_id" : "windows_device_id") ?? ""),
        ...(toolsEnabled && toolsQuery.data?.editable ? { tool_selection: toolValue, expected_tools_revision: toolDraft?.revision ?? toolsQuery.data.tools_revision } : {}),
        ...(collaborationDraft ? { collaboration: collaborationDraft } : {}),
      });
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Request failed");
    }
  }


  return (
    <form
      className={`${styles.dialog} ${styles.settingsForm}`}
      onSubmit={onSubmit}
      onInvalid={(event) => {
        const input = event.target as HTMLInputElement;
        setError(
          input.name === "name" ? "Enter a bot name."
            : input.name === "model" ? "Enter a model." : input.validationMessage,
        );
      }}
    >
      <div className={styles.settingsBody} role="region" aria-label="Bot settings fields" tabIndex={0}>
        <div className={styles.settingsColumns}>
          <section className={styles.settingsColumn} aria-label="Bot details and prompts">
            <h3>Bot details</h3>
            <p>Framework: {bot.framework}</p>
            <label>
              Name
              <input
                name="name"
                defaultValue={bot.name}
                required
                disabled={save.isPending}
                key={bot.updated_at + bot.name}
              />
            </label>
            <label>
              API key
              <select
                name="credential_id"
                disabled={save.isPending || credentials.isPending}
                defaultValue={bot.credential_id ?? ""}
                key={`${bot.updated_at}:${bot.credential_id ?? ""}:${matching.map((item) => item.id).join()}`}
              >
                {matching.length === 0 ? (
                  <option value="">No matching key</option>
                ) : null}
                {matching.map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.label}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Model
              <input
                name="model"
                required
                disabled={save.isPending}
                defaultValue={bot.model}
                key={bot.updated_at + bot.model}
              />
            </label>
            <label>
              Instructions
              <textarea
                name="instructions"
                rows={4}
                disabled={save.isPending}
                value={instructions}
                onChange={(event) => setInstructions(event.target.value)}
              />
            </label>
            <label>
              Default Prompt (optional)
              <textarea
                name="default_prompt"
                rows={4}
                maxLength={8000}
                disabled={save.isPending}
                defaultValue={bot.default_prompt ?? ""}
                key={`${bot.id}:${bot.updated_at}:${bot.default_prompt ?? ""}`}
                aria-describedby={`default-prompt-help-${bot.id}`}
              />
            </label>
            <p id={`default-prompt-help-${bot.id}`}>
              Adds a button in the message panel to fill your draft. Leave blank to hide it.
            </p>
            {collaboration.data ? <CollaborationFields saved={collaboration.data} draft={collaborationDraft} disabled={save.isPending || !toolsQuery.data?.editable} onChange={value => { setCollaborationDraft(value); if (toolsQuery.data) changeTools(value.enabled ? [...toolValue.filter(t => t.library_id !== messagingTool.library_id), messagingTool] : toolValue.filter(t => t.library_id !== messagingTool.library_id)); }} /> : null}
            {collaborationDraft ? <button type="button" onClick={async () => { await collaboration.refetch(); await toolsQuery.refetch(); setCollaborationDraft(null); setToolDraft(null); setError(""); }}>Reload collaboration and tools</button> : null}
          </section>
          <section className={styles.settingsColumn} aria-label="Computer and approvals">
            {toolsEnabled ? toolsQuery.data ? <>
              <ToolLibraryPicker framework={bot.framework} value={toolValue} onChange={changeTools} state={toolsQuery.data} disabled={save.isPending || !toolsQuery.data.editable} />
              <button type="button" disabled={save.isPending} onClick={async () => { const result = await toolsQuery.refetch(); if (result.data) { setToolDraft({ selection: result.data.tool_selection, revision: result.data.tools_revision }); setError(""); } }}>Reload saved tools</button>
            </> : <p role="status">{toolsQuery.isError ? "Could not load selected tools." : "Loading selected tools?"} <button type="button" onClick={() => void toolsQuery.refetch()}>Retry</button></p> : null}
            <h3>Computer and approvals</h3>
            <AutopilotToggle botId={bot.id} showUnavailable />
            {!["ufo", "open_interface"].includes(bot.framework) ? <CloudComputerSettings botId={bot.id} disabled={save.isPending} onSelection={setCloudSelection} onBusyChange={setCloudBusy} /> : null}
            {bot.framework === "open_interface" ? <MacComputerSettings botId={bot.id} framework={bot.framework} disabled={save.isPending} onBusyChange={setWindowsBusy} /> : <WindowsComputerSettings
              botId={bot.id}
              framework={bot.framework}
              disabled={save.isPending}
              onBusyChange={setWindowsBusy}
            />}
            {session?.protocol === 2 ? <ApprovalPolicies botId={bot.id} /> : null}
          </section>
        </div>
      </div>
      <div className={styles.settingsFooter} role="group" aria-label="Bot settings actions">
        {error ? <p className="error" role="alert">{error}</p> : null}
        {save.isSuccess && !onSaved ? <p role="status">Settings saved.</p> : null}
        <div className={styles.actions}>
          <button
            type="button"
            disabled={save.isPending || remove.isPending}
            onClick={() => {
              if (window.confirm(`Delete ${bot.name}?`)) remove.mutate();
            }}
          >
            Delete
          </button>
          <button
            className="primary"
            type="submit"
            disabled={save.isPending || windowsBusy || cloudBusy || remove.isPending || credentials.isPending || (toolsEnabled && !toolsQuery.data)}
          >
            {save.isPending ? "Saving…" : "Save"}
          </button>
        </div>
      </div>
    </form>
  );
}
