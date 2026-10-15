import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useSearchParams } from "react-router-dom";
import { api, type Bot } from "../../api/client";
import { CaptureRetentionSettings } from "./CaptureRetentionSettings";
import { CollaborationSettings } from "./ChannelPanel";
import { post, type Workspace, type Preferences } from "./workspaceApi";
import { Members } from "./Members";
import { GroupsPanel } from "./GroupsPanel";
import { RoutinesPanel } from "./RoutinesPanel";
import { ToolkitPanel } from "./ToolkitPanel";
import { Notifications } from "./Notifications";
import { SearchPanel } from "./SearchPanel";
import { Profile } from "./Profile";
import { SharedComputerSettings } from "./SharedComputerSettings";
import { ImportWorkflowDialog } from "../workflow-imports/ImportWorkflowDialog";
import { DeletionPanel } from "../workspace-deletion/DeletionPanel";
import "./center.css";

export function WorkspaceCenter() {
  const client = useQueryClient();
  const [searchParams] = useSearchParams();
  const workspaces = useQuery({
    queryKey: ["workspaces"],
    queryFn: () => api<Workspace[]>("/api/workspaces"),
    refetchInterval: 5000,
  });
  const preferences = useQuery({
    queryKey: ["preferences"],
    queryFn: () => api<Preferences>("/api/preferences"),
  });
  const [selected, setSelected] = useState("");
  const requested = selected || searchParams.get("workspace") || preferences.data?.workspace_id;
  const personal = workspaces.data?.find(w => w.role === "owner" && w.id.startsWith("personal_"));
  const wid = workspaces.data?.some(w => w.id === requested) ? requested! : personal?.id || workspaces.data?.[0]?.id || "";
  const [tab, setTab] = useState(searchParams.get("tab") || "members");
  const [error, setError] = useState("");
  const [name, setName] = useState("");
  const [importOpen, setImportOpen] = useState(false);
  const bots = useQuery({
    queryKey: ["workspace-bots", wid],
    queryFn: () => api<Bot[]>(`/api/bots?workspace_id=${wid}`),
    enabled: !!wid,
  });
  const [botId, setBotId] = useState("");
  const bid = bots.data?.some((b) => b.id === botId)
    ? botId
    : (bots.data?.[0]?.id ?? "");
  const owner = workspaces.data?.find((w) => w.id === wid)?.role === "owner";
  async function switchWorkspace(id: string) {
    setSelected(id);
    if (!preferences.data) return;
    try {
      await post("/api/preferences", { ...preferences.data, workspace_id: id });
      await client.invalidateQueries({ queryKey: ["preferences"] });
      await client.invalidateQueries({ queryKey: ["bots"] });
    } catch (e) {
      setError(String(e));
    }
  }
  return (
    <section className="workspace-center">
      <div className="center-heading">
        <div>
          <h1>Workspace settings</h1>
          <p className="muted">
            Manage people, shared work, reusable tools, and routines.
          </p>
        </div>
        <Link to="/overview">Back to bots</Link>
      </div>
      <div className="center-toolbar">
        <label>
          Workspace
          <select
            value={wid}
            onChange={(e) => void switchWorkspace(e.target.value)}
          >
            {workspaces.data?.map((w) => (
              <option key={w.id} value={w.id}>
                {w.name} · {w.role}
              </option>
            ))}
          </select>
        </label>
        <form
          className="row"
          onSubmit={async (e) => {
            e.preventDefault();
            try {
              const result = await post<Workspace>("/api/workspaces", { name });
              setName("");
              await workspaces.refetch();
              await switchWorkspace(result.id);
            } catch (e) {
              setError(String(e));
            }
          }}
        >
          <input
            aria-label="New workspace name"
            placeholder="New workspace name"
            required
            maxLength={100}
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
          <button>Create workspace</button>
        </form>
        <button type="button" onClick={() => setImportOpen(true)}>Import workflow</button>
      </div>
      {preferences.data?.onboarding === "new" ? (
        <div className="center-card">
          <h2>Start with a real task</h2>
          <ol>
            <li>
              <Link to="/keys">Connect a model API key</Link>.
            </li>
            <li>Create a bot from the New bot button and select that key.</li>
            <li>
              Open its chat, submit a small task, and review any approval
              requests.
            </li>
          </ol>
          <button
            onClick={async () => {
              if (!preferences.data) return;
              await post("/api/preferences", {
                ...preferences.data,
                onboarding: "dismissed",
              });
              void preferences.refetch();
            }}
          >
            Dismiss tour
          </button>
          <button
            onClick={async () => {
              if (!preferences.data) return;
              await post("/api/preferences", {
                ...preferences.data,
                onboarding: "completed",
              });
              void preferences.refetch();
            }}
          >
            Mark tour complete
          </button>
        </div>
      ) : null}
      <nav className="center-tabs" aria-label="Workspace settings sections">
        {[
          "members",
          "groups",
          "collaboration",
          "storage",
          "computer",
          "routines",
          "toolkit",
          "notifications",
          "search",
          "profile",
        ].map((t) => (
          <button
            key={t}
            aria-pressed={tab === t}
            onClick={() => {
              setTab(t);
              setError("");
            }}
          >
            {t[0].toUpperCase() + t.slice(1)}
          </button>
        ))}
      </nav>
      {error ? <p role="alert">{error}</p> : null}
      {wid && tab === "storage" ? <CaptureRetentionSettings key={wid} wid={wid} /> : null}
      {wid && tab === "computer" ? <SharedComputerSettings key={wid} wid={wid} owner={!!owner} /> : null}
      {wid && tab === "collaboration" ? <CollaborationSettings key={wid} wid={wid} /> : null}
      {tab === "members" || tab === "toolkit" ? (
        <label className="center-bot">
          Bot
          <select
            aria-label="Settings bot"
            value={bid}
            onChange={(e) => setBotId(e.target.value)}
          >
            {bots.data?.map((b) => (
              <option key={b.id} value={b.id}>
                {b.name}
              </option>
            ))}
          </select>
        </label>
      ) : null}
      {wid && tab === "members" ? (
        <Members
          key={wid}
          wid={wid}
          bid={bid}
          owner={!!owner}
          onError={setError}
        />
      ) : null}
      {wid && tab === "groups" ? (
        <GroupsPanel
          key={wid}
          wid={wid}
          bots={bots.data ?? []}
          onError={setError}
        />
      ) : null}
      {wid && tab === "routines" ? (
        <RoutinesPanel
          key={wid}
          wid={wid}
          bots={bots.data ?? []}
          onError={setError}
        />
      ) : null}
      {bid && tab === "toolkit" ? (
        <ToolkitPanel key={bid} bid={bid} onError={setError} />
      ) : null}
      {tab === "notifications" ? <Notifications /> : null}
      {wid && tab === "search" ? <SearchPanel wid={wid} /> : null}
      {tab === "profile" && preferences.data ? (
        <Profile
          key={preferences.data.revision}
          preferences={preferences.data}
          onSaved={() => void preferences.refetch()}
          onError={setError}
        />
      ) : null}
      <ImportWorkflowDialog open={importOpen} onClose={() => setImportOpen(false)} onCreated={async result => {
        setSelected(result.workspace_id);
        await Promise.all(["workspaces", "workspace-bots", "bots", "channel", "directory", "workspace-computer"].map(key => client.invalidateQueries({ queryKey: [key] })));
        const current = await api<Preferences>("/api/preferences");
        await post("/api/preferences", { ...current, workspace_id: result.workspace_id });
        await client.invalidateQueries({ queryKey: ["preferences"] });
      }} />
      <DeletionPanel workspace={workspaces.data?.find(w => w.id === wid)} onDeleted={() => { setSelected(personal?.id || ""); setBotId(""); }} />
    </section>
  );
}
