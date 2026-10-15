import { useEffect, useState } from "react";
import type { FormEvent } from "react";
import { Dialog } from "../../components/ui/Dialog";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";

import {
  api,
  providersFor,
  suggestedModel,
  type Bot,
  type Credential,
  type ToolSelection,
} from "../../api/client";
import styles from "./dialog.module.css";

import { ToolLibraryPicker } from "./ToolLibraryPicker";
import { messagingTool, type ChannelSnapshot } from "../workspace/channel";

const FRAMEWORKS = ["anthropic", "microsoft"];

function frameworkWithKey(credentials: Credential[]): string {
  const match = FRAMEWORKS.find((framework) =>
    credentials.some((item) =>
      (providersFor(framework) ?? []).includes(item.provider),
    ),
  );
  return match ?? "anthropic";
}

type Props = {
  open: boolean;
  onClose: () => void;
  onCreated: (bot: Bot) => void;
  initialFramework?: string;
};

export function CreateBotDialog({
  open,
  onClose,
  onCreated,
  initialFramework,
}: Props) {
  const capabilities = useQuery({
    queryKey: ["capabilities"],
    queryFn: () =>
      api<{
        frameworks?: string[];
        tool_libraries?: boolean;
        workspace_bot_channels?: boolean;
      }>("/api/capabilities"),
  });
  const preferences = useQuery({
    queryKey: ["preferences"],
    queryFn: () => api<{ workspace_id: string | null }>("/api/preferences"),
    enabled: open && !!capabilities.data?.workspace_bot_channels,
  });
  const workspaces = useQuery({
    queryKey: ["workspaces"],
    queryFn: () => api<{ id: string }[]>("/api/workspaces"),
    enabled: open && !!capabilities.data?.workspace_bot_channels,
  });
  const wid = preferences.data?.workspace_id || workspaces.data?.[0]?.id;
  const channel = useQuery({
    queryKey: ["channel", wid],
    queryFn: () => api<ChannelSnapshot>(`/api/workspaces/${wid}/channel`),
    enabled: open && !!wid && !!capabilities.data?.workspace_bot_channels,
  });
  const [join, setJoin] = useState<boolean | null>(null);
  const frameworks = capabilities.data?.frameworks ?? FRAMEWORKS;
  const [tools, setTools] = useState<ToolSelection[]>([]);
  const [error, setError] = useState("");
  const [framework, setFramework] = useState("anthropic");
  const [frameworkTouched, setFrameworkTouched] = useState(false);
  const [credentialId, setCredentialId] = useState("");
  const [model, setModel] = useState("claude-sonnet-5");
  const [name, setName] = useState("");
  const [instructions, setInstructions] = useState("");
  const credentials = useQuery({
    queryKey: ["credentials"],
    queryFn: () => api<Credential[]>("/api/credentials"),
  });

  const [seenOpen, setSeenOpen] = useState(open);
  if (open !== seenOpen) {
    setSeenOpen(open);
    if (open) {
      setName("");
      setTools([]);
      setJoin(null);
      setInstructions("");
      setError("");
      setFrameworkTouched(false);
    }
  }

  const selectedFramework = frameworkTouched
    ? framework
    : (initialFramework ?? frameworkWithKey(credentials.data ?? []));
  const allowed = providersFor(selectedFramework) ?? [];
  const matching = (credentials.data ?? []).filter((item) =>
    allowed.includes(item.provider),
  );

  useEffect(() => {
    if (!open) return;
    const items = (credentials.data ?? []).filter((item) =>
      (providersFor(selectedFramework) ?? []).includes(item.provider),
    );
    const next = items.find((item) => item.id === credentialId) ?? items[0];
    if (!next) {
      if (credentialId) setCredentialId("");
      return;
    }
    if (next.id !== credentialId) {
      setCredentialId(next.id);
      setModel(suggestedModel(next.provider));
    }
  }, [open, selectedFramework, credentials.data, credentialId]);

  if (!open) return null;
  const joining = join ?? !!channel.data?.enroll_future;
  const selectedTools = joining
    ? [
        ...tools.filter((t) => t.library_id !== messagingTool.library_id),
        messagingTool,
      ]
    : tools;

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    if (capabilities.isPending) return;
    if (!frameworks.includes(selectedFramework)) {
      setError(
        "This framework is unavailable. Restart the updated control backend and try again.",
      );
      return;
    }
    if (!credentialId) {
      setError("Add an API key for this framework first.");
      return;
    }
    try {
      const bot = await api<Bot>("/api/bots", {
        method: "POST",
        body: JSON.stringify({
          name,
          framework: selectedFramework,
          instructions,
          credential_id: credentialId,
          model,
          ...(capabilities.data?.tool_libraries
            ? { tool_selection: selectedTools }
            : {}),
          ...(capabilities.data?.workspace_bot_channels
            ? { join_workspace_channel: joining }
            : {}),
        }),
      });
      onCreated(bot);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Request failed");
    }
  }

  return (
    <Dialog
      open={open}
      title="New bot"
      onClose={onClose}
      className={styles.settingsDialog}
    >
      <form
        className={`${styles.dialog} ${styles.settingsForm}`}
        onSubmit={onSubmit}
      >
        <div
          className={styles.settingsBody}
          role="region"
          aria-label="New bot fields"
          tabIndex={0}
        >
          <div className={styles.settingsColumns}>
            <section className={styles.settingsColumn} aria-label="Bot details">
              <h3>Bot details</h3>
              <label>
                Name
                <input
                  name="name"
                  required
                  value={name}
                  onChange={(event) => setName(event.target.value)}
                />
              </label>
              <label>
                Framework
                <select
                  name="framework"
                  value={selectedFramework}
                  onChange={(event) => {
                    setFrameworkTouched(true);
                    setError("");
                    setFramework(event.target.value);
                  }}
                >
                  {!frameworks.includes(selectedFramework) ? (
                    <option value={selectedFramework}>
                      {selectedFramework}
                    </option>
                  ) : null}
                  {frameworks.map((name) => (
                    <option key={name} value={name}>
                      {name === "ufo"
                        ? "Microsoft UFO · Windows desktop"
                        : name}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                API key
                <select
                  name="credential_id"
                  value={credentialId}
                  onChange={(event) => {
                    const next = matching.find(
                      (item) => item.id === event.target.value,
                    );
                    setCredentialId(event.target.value);
                    if (next) setModel(suggestedModel(next.provider));
                  }}
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
              {matching.length === 0 ? (
                <p className="error">
                  No API key for this framework.{" "}
                  <Link to="/keys" onClick={onClose}>
                    Add one
                  </Link>{" "}
                  first.
                </p>
              ) : null}
              <label>
                Model
                <input
                  name="model"
                  required
                  value={model}
                  placeholder={suggestedModel(
                    matching.find((item) => item.id === credentialId)
                      ?.provider ?? selectedFramework,
                  )}
                  onChange={(event) => setModel(event.target.value)}
                />
              </label>
            </section>
            <section
              className={styles.settingsColumn}
              aria-label="Instructions and tools"
            >
              <h3>Instructions and tools</h3>
              <label>
                Instructions
                <textarea
                  name="instructions"
                  rows={4}
                  value={instructions}
                  onChange={(event) => setInstructions(event.target.value)}
                />
              </label>
              {capabilities.data?.workspace_bot_channels ? (
                <label className="channel-check">
                  <input
                    type="checkbox"
                    checked={joining}
                    onChange={(e) => {
                      setJoin(e.target.checked);
                      if (!e.target.checked)
                        setTools((t) =>
                          t.filter(
                            (item) =>
                              item.library_id !== messagingTool.library_id,
                          ),
                        );
                    }}
                  />
                  Join workspace channel
                </label>
              ) : null}
              {joining ? (
                <p>
                  Publishes this bot's name to workspace members and enables
                  peer requests. Set its public purpose in Bot settings.
                </p>
              ) : null}
              {capabilities.data?.tool_libraries ? (
                <ToolLibraryPicker
                  framework={selectedFramework}
                  value={selectedTools}
                  onChange={(value) => {
                    setTools(value);
                    setJoin(
                      value.some(
                        (t) => t.library_id === messagingTool.library_id,
                      ),
                    );
                  }}
                />
              ) : null}
            </section>
          </div>
        </div>
        <footer className={styles.settingsFooter}>
          {error ? (
            <p className="error" role="alert">
              {error}
            </p>
          ) : null}
          <div
            className={styles.actions}
            role="group"
            aria-label="New bot actions"
          >
            <button type="button" onClick={onClose}>
              Cancel
            </button>
            <button
              className="primary"
              type="submit"
              disabled={capabilities.isPending}
            >
              Add bot
            </button>
          </div>
        </footer>
      </form>
    </Dialog>
  );
}
