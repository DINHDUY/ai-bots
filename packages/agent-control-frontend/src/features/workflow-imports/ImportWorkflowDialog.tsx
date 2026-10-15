import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api, type Credential } from "../../api/client";
import type { ImportResult } from "../../api/imports.generated";
import { Dialog } from "../../components/ui/Dialog";
import { AgentFileCard } from "./AgentFileCard";
import { RuntimeFields } from "./RuntimeFields";
import { useWorkflowImport } from "./useWorkflowImport";
import "./import.css";

export function ImportWorkflowDialog({ open, onClose, onCreated }: {
  open: boolean; onClose: () => void; onCreated: (result: ImportResult) => Promise<void>;
}) {
  const flow = useWorkflowImport(onCreated);
  const credentials = useQuery({ queryKey: ["credentials"], queryFn: () => api<Credential[]>("/api/credentials"), enabled: open });
  const capabilities = useQuery({ queryKey: ["capabilities"], queryFn: () => api<{ workflow_imports?: boolean }>("/api/capabilities"), enabled: open });
  const available = capabilities.data?.workflow_imports === true;
  const defaults = flow.draft.defaults ?? { framework: "microsoft" };
  return <Dialog open={open} onClose={onClose} title="Import workflow" className="workflow-import-dialog">
    {flow.result ? <section aria-label="Import complete">
      <h3>{flow.deleted ? "This imported workspace was deleted" : `${flow.result.workspace_name} is ready`}</h3>
      {!flow.deleted ? <><p>{flow.result.bots.length} bots imported. Messaging is enabled for all bots.</p>
      <ul>{flow.result.bots.map(bot => <li key={bot.bot_id}><Link to={`/bots/${bot.bot_id}`} onClick={onClose}>{bot.name}</Link></li>)}</ul>
      <p>The shared computer has not been created. Channel conversations can start now; computer work needs a running computer.</p></> : <p>The original import receipt is retained. You can import the files again to create a new workspace.</p>}
      <div className="import-actions">{!flow.deleted ? <><Link to={`/channel?workspace=${flow.result.workspace_id}`} onClick={onClose}>Open Bot channel</Link><Link to={`/workspace?tab=computer&workspace=${flow.result.workspace_id}`} onClick={onClose}>Set up shared computer</Link></> : null}<button type="button" onClick={flow.reset}>Import another workflow</button></div>
    </section> : <>
      <p>Turn agent Markdown files into bots in a new workspace. Each file becomes one bot; frontmatter is removed from its instructions.</p>
      {capabilities.isPending ? <p role="status">Checking import availability…</p> : !available ? <p role="alert">Workflow import requires workspace channels, tool libraries, and shared computers on the backend.</p> : null}
      {flow.pendingId ? <section className="import-recovery"><p>An import may already have completed. Check its result before starting another.</p><button type="button" disabled={flow.busy} onClick={() => void flow.recover()}>Check import result</button></section> : null}
      <fieldset disabled={flow.locked || !available}>
        <label>New workspace name<input maxLength={100} value={flow.draft.workspace_name} onChange={event => flow.change({ ...flow.draft, workspace_name: event.target.value })} /></label>
        <div className="import-drop" onDragOver={event => event.preventDefault()} onDrop={event => {
          event.preventDefault(); if (available && !flow.locked) void flow.files(Array.from(event.dataTransfer.files));
        }}><label>Agent Markdown files<input type="file" accept=".md" multiple onChange={event => {
          void flow.files(Array.from(event.target.files ?? [])); event.target.value = "";
        }} /></label><p>Drop files here or choose files. Up to 50 files, 64 KiB each; instructions up to 16,000 characters.</p></div>
        <h3>Default runtime for imported bots</h3>
        {credentials.isError ? <p role="alert">Could not load API keys. <button type="button" onClick={() => void credentials.refetch()}>Reload API keys</button></p> : null}
        <RuntimeFields value={defaults} credentials={credentials.data ?? []} onChange={next => flow.change({ ...flow.draft, defaults: next })} />
        <button type="button" onClick={() => void credentials.refetch()}>Refresh API keys</button>
        <div className="import-summary"><strong>Shared Docker computer · Messaging enabled for all bots</strong><p>Bots share files, browser tabs, desktop state, and processes. Importing creates no running computer or model task.</p></div>
        {flow.draft.files.map(file => <AgentFileCard key={file.file_id} file={file}
          preview={flow.preview?.files.find(item => item.file_id === file.file_id)} error={flow.fileErrors[file.file_id]}
          defaults={defaults} credentials={credentials.data ?? []}
          onRemove={() => flow.change({ ...flow.draft, files: flow.draft.files.filter(item => item.file_id !== file.file_id) })}
          onReplace={next => void flow.files([next], file.file_id)}
          onChange={overrides => flow.change({ ...flow.draft, files: flow.draft.files.map(item => item.file_id === file.file_id ? { ...item, overrides } : item) })} />)}
      </fieldset>
      {flow.preview?.errors?.map((error, index) => <p key={index} role="alert" className="error">{error.message}</p>)}
      {!flow.reviewed && flow.preview ? <p>Files or settings changed. Preview again before importing.</p> : null}
      {flow.reviewed && flow.preview?.valid ? <p role="status">{flow.preview.files.length} agents validated and ready to import.</p> : null}
      <div className="import-actions">
        <button type="button" disabled={flow.locked || !available || !flow.draft.files.length} onClick={() => void flow.review()}>Preview agents</button>
        <button type="button" className="primary" disabled={flow.busy || !available || (!flow.locked && (!flow.reviewed || !flow.preview?.valid))} onClick={() => void flow.commit()}>{flow.busy ? "Working…" : flow.pendingId ? "Retry same import" : "Import workflow"}</button>
      </div>
    </>}
    {flow.error ? <p role="alert" className="error">{flow.error}</p> : null}
  </Dialog>;
}
