import { useEffect, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../../api/client";
import styles from "./dialog.module.css";

import { applyCloudSelection, type CloudSelection, type ComputeConfig, type Profile } from "./cloudSelection";

export function CloudComputerSettings({ botId, disabled, onSelection, onBusyChange }: {
  botId: string; disabled: boolean; onSelection: (value: CloudSelection | null) => void; onBusyChange: (busy: boolean) => void;
}) {
  const client = useQueryClient();
  const capabilities = useQuery({ queryKey: ["capabilities"], queryFn: () => api<{ cloud_computers?: boolean }>("/api/capabilities"), staleTime: 60_000 });
  const available = capabilities.data?.cloud_computers === true;
  const config = useQuery({ queryKey: ["compute-config", botId], queryFn: () => api<ComputeConfig>(`/api/bots/${botId}/compute-config`), enabled: available, refetchInterval: 5000 });
  const profiles = useQuery({ queryKey: ["compute-profiles", config.data?.workspace_id], enabled: !!config.data?.workspace_id, queryFn: () => api<{ profiles: Profile[] }>(`/api/workspaces/${config.data!.workspace_id}/compute-profiles`) });
  const [draft, setDraft] = useState<CloudSelection | null>(null);
  const selection = draft ?? config.data;
  const [resource, setResource] = useState("");
  const [hostKey, setHostKey] = useState("");
  const [grant, setGrant] = useState<{ code: string; binding_id: string; expires_at: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  useEffect(() => { onSelection(draft); }, [draft, onSelection]);
  useEffect(() => { onBusyChange(busy); }, [busy, onBusyChange]);
  const profile = profiles.data?.profiles.find(p => p.id === selection?.profile_id);
  async function perform(work: () => Promise<void>) {
    setBusy(true); setError(""); setMessage("");
    try {
      await work();
      await client.invalidateQueries({ queryKey: ["compute-config", botId] });
      await client.invalidateQueries({ queryKey: ["computer", botId] });
    } catch (e) { setError(e instanceof Error ? e.message : String(e)); }
    finally { setBusy(false); }
  }
  async function save() {
    if (!selection) throw new Error("Select a computer profile.");
    const result = await applyCloudSelection(botId, selection, config.data);
    client.setQueryData(["compute-config", botId], result);
    setDraft(null);
    return result;
  }
  if (!available) return null;
  return <fieldset className={styles.computerSettings} disabled={disabled || busy}>
    <legend>Computer</legend>
    <p>Choose where this bot runs. Close its current computer before changing providers.</p>
    <label>Computer provider
      <select aria-label="Computer provider" value={selection?.provider ?? "docker"} onChange={e => {
        const chosen = profiles.data?.profiles.find(p => p.provider === e.target.value);
        setDraft({ provider: e.target.value, profile_id: chosen?.id ?? null, ownership: "attached" }); setResource("");
      }}>
        <option value="docker">Local Docker</option>
        {[...new Set(profiles.data?.profiles.map(p => p.provider) ?? [])].map(p => <option key={p} value={p}>{p === "azure_ml_compute_instance" ? "Azure ML Compute Instance" : "Azure Linux VM"}</option>)}
      </select>
    </label>
    {selection && selection.provider !== "docker" ? <>
      <label>Approved compute profile<select aria-label="Approved compute profile" value={selection.profile_id ?? ""} onChange={e => { setDraft({ ...selection, profile_id: e.target.value }); setResource(""); }}>
        <option value="" disabled>Select a profile</option>
        {profiles.data?.profiles.filter(p => p.provider === selection.provider).map(p => <option key={p.id} value={p.id}>{p.name}</option>)}
      </select></label>
      <label>Computer ownership<select aria-label="Computer ownership" value={selection.ownership} onChange={e => setDraft({ ...selection, ownership: e.target.value })}>
        <option value="attached">Attach existing computer</option>
        {profile?.allowed_operations.includes("create") ? <option value="managed">Create managed computer</option> : null}
      </select></label>
      {profile ? <p>{profile.region} · {profile.default_size} · {profile.storage_policy.replaceAll("_", " ")}. Retained disks may continue to incur charges after stopping.</p> : null}
      {!config.data?.binding && selection.ownership === "attached" ? <label>Approved Azure computer<select aria-label="Approved Azure computer" value={resource} onChange={e => setResource(e.target.value)}>
        <option value="">Select a computer</option>
        {profile?.resources.map(id => <option key={id} value={id}>{id.split("/").at(-1)}</option>)}
      </select></label> : null}
    </> : null}
    {draft ? <p role="status">Computer selection not saved. Click Save or Apply computer selection.</p> : null}
    <div className={styles.computerActions}>
      <button type="button" disabled={!draft || !config.data} onClick={() => void perform(async () => { await save(); setMessage("Computer selection saved."); })}>Apply computer selection</button>
      {selection?.provider !== "docker" && !config.data?.binding ? <button type="button" disabled={!config.data || !profile || (selection?.ownership === "attached" && !resource)} onClick={() => void perform(async () => {
        const selected = await save();
        const computer = await api<{ computer: { generation: number } | null }>(`/api/bots/${botId}/computer`);
        const result = await api<{ detail?: string }>(`/api/bots/${botId}/${selected.ownership === "managed" ? "lifecycle/create" : "computer/attach"}`, {
          method: "POST", body: JSON.stringify({ request_id: crypto.randomUUID(), generation: computer.computer?.generation ?? 0, ...(selected.ownership === "attached" ? { resource_id: resource, expected_revision: selected.revision } : {}) }),
        });
        setMessage(result.detail || "Request accepted. Progress is shown in Live Cloud Computer.");
      })}>{selection?.ownership === "managed" ? "Create managed computer" : "Attach computer"}</button> : null}
    </div>
    {config.data?.binding ? <details><summary>Host connection</summary>
      <p>Computer: {config.data.binding.resource_id.split("/").at(-1)} · {config.data.binding.status}</p>
      <p>Install the trusted Linux host service, run <code>sudo agentbot-computer-agent identity</code>, and enter its host fingerprint here.</p>
      <label>Host fingerprint<input value={hostKey} onChange={e => setHostKey(e.target.value.trim())} autoComplete="off" /></label>
      <button type="button" disabled={!/^[a-f0-9]{64}$/.test(hostKey)} onClick={() => void perform(async () => {
        setGrant(await api(`/api/bots/${botId}/computer/enrollment`, { method: "POST", body: JSON.stringify({ request_id: crypto.randomUUID(), host_key: hostKey }) }));
      })}>Issue one-time enrollment code</button>
      {grant ? <div role="status"><p>Run <code>sudo agentbot-computer-agent enroll</code> on that host. Binding: {grant.binding_id}. Code expires at {new Date(grant.expires_at).toLocaleTimeString()}.</p><input aria-label="Host enrollment code" value={grant.code} readOnly onFocus={e => e.target.select()} /><button type="button" onClick={() => setGrant(null)}>Hide code</button></div> : null}
    </details> : null}
    {message ? <p role="status">{message}</p> : null}
    {error || config.error || profiles.error ? <p role="alert">{error || config.error?.message || profiles.error?.message}</p> : null}
  </fieldset>;
}
