import { useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api, ApiError } from "../../api/client";
import type { DeleteCommand, DeletionHistory, DeletionPreview, DeletionResult } from "../../api/deletions.generated";
import { Dialog } from "../../components/ui/Dialog";
import { post, type Workspace } from "../workspace/workspaceApi";
import { RetainedInventory } from "./RetainedInventory";
import "./deletion.css";

const countLabels: Record<string, string> = { bots: "Bots", workspace_members: "People", messages: "Chat messages", channel_messages: "Bot channel messages", groups: "Groups", routines: "Routines", skill_versions: "Saved skills", connections: "Connections", file_blobs: "Stored artifacts", uploads: "Uploads", captures: "Screenshots", stored_bytes: "Stored bytes" };
const recoveryKey = "workspace-deletion-pending";
type Pending = { wid: string; command: DeleteCommand };
function savedPending(): Pending | null {
  try {
    const value = JSON.parse(sessionStorage.getItem(recoveryKey) ?? "null") as Pending | null;
    return value?.wid && value.command?.request_id ? value : null;
  } catch { return null; }
}

export function DeletionPanel({ workspace, onDeleted }: {
  workspace?: Workspace; onDeleted: () => void;
}) {
  const queries = useQueryClient();
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const working = useRef(false);
  const [pending, setPending] = useState<Pending | null>(savedPending);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [cursor, setCursor] = useState(0);
  const preview = useQuery({
    queryKey: ["workspace-deletion-preview", workspace?.id],
    queryFn: () => api<DeletionPreview>(`/api/workspaces/${workspace!.id}/deletion-preview`),
    enabled: open && !!workspace && !pending,
    staleTime: 0,
  });
  const history = useQuery({
    queryKey: ["workspace-deletions", cursor],
    queryFn: () => api<DeletionHistory>(`/api/workspace-deletions?cursor=${cursor}`),
    refetchInterval: 2000,
  });

  async function finished(result: DeletionResult) {
    setPending(null); sessionStorage.removeItem(recoveryKey); setOpen(false);
    setName(""); setError("");
    setNotice(result.cleanup.state === "complete" ? "Workspace deleted." : "Workspace deleted; file cleanup pending.");
    onDeleted();
    await queries.cancelQueries({ predicate: query => query.queryKey.includes(result.workspace_id) });
    queries.removeQueries({ predicate: query => query.queryKey.includes(result.workspace_id) });
    // Deletion invalidates bot permissions as well as catalog lists.
    await queries.invalidateQueries();
  }

  async function run(action: () => Promise<void>) {
    if (working.current) return;
    working.current = true; setBusy(true); setError("");
    try { await action(); }
    catch (caught) { setError(String(caught)); }
    finally { working.current = false; setBusy(false); }
  }

  async function submit(original?: Pending) {
    const current = original ?? (workspace && preview.data ? {
      wid: workspace.id,
      command: { request_id: crypto.randomUUID(), preview_digest: preview.data.preview_digest, confirm_name: name },
    } : null);
    if (!current) return;
    setPending(current);
    // Only the confirmation and digest are stored; no workspace contents are copied.
    sessionStorage.setItem(recoveryKey, JSON.stringify(current));
    try {
      await finished(await post<DeletionResult>(`/api/workspaces/${current.wid}/deletions`, current.command));
    } catch (caught) {
      if (caught instanceof ApiError && [400, 401, 403, 404, 405, 409, 422].includes(caught.status)) {
        // A racing request may already have committed; history preserves that result.
        setPending(null); sessionStorage.removeItem(recoveryKey);
        void history.refetch(); void preview.refetch();
        throw new Error(`${caught.message} Review the current deletion preview or history.`, { cause: caught });
      }
      const failure = caught instanceof ApiError ? `The server returned HTTP ${caught.status}: ${caught.message}. ` : "";
      throw new Error(`${failure}Deletion result is unknown. Check its status or retry the original request.`, { cause: caught });
    }
  }

  return <details className="center-card workspace-deletion">
    <summary>Delete workspace</summary>
    {workspace?.role === "owner" ? workspace.id.startsWith("personal_")
      ? <p>The Personal workspace cannot be deleted.</p>
      : <><p>Delete this workspace and all its bots, conversations, routines, and stored files.</p>
        <button type="button" className="danger" disabled={!!pending || busy} onClick={() => { setName(""); setError(""); setOpen(true); }}>Delete workspace</button></>
      : <p>Only the workspace owner can delete it.</p>}
    {notice ? <p role="status">{notice}</p> : null}
    {error ? <p role="alert">{error}</p> : null}
    {pending ? <div role="status"><p>A deletion request needs confirmation of its result.</p>
      <button disabled={busy} onClick={() => void run(async () => {
        try { await finished(await api<DeletionResult>(`/api/workspace-deletions/${pending.command.request_id}`)); }
        catch (caught) {
          if (caught instanceof ApiError && caught.status === 404) throw new Error("No receipt yet. Retry the original request or check again.", { cause: caught });
          throw caught;
        }
      })}>Check deletion status</button>
      <button disabled={busy} onClick={() => void run(() => submit(pending))}>Retry original deletion</button>
    </div> : null}
    <Dialog open={open} title="Delete workspace and contents" onClose={() => { if (!busy) setOpen(false); }}>
      {preview.isPending ? <p>Loading deletion preview…</p> : null}
      {preview.error ? <p role="alert">{String(preview.error)}</p> : null}
      {preview.data ? <>
        <p><strong>{preview.data.workspace_name}</strong> and its contents will be permanently deleted.</p>
        <ul>{preview.data.bots.map(bot => <li key={bot.id}>{bot.name}</li>)}</ul>
        <dl className="deletion-counts">{Object.entries(preview.data.counts).filter(([label, value]) => countLabels[label] && value > 0).map(([label, value]) =>
          <div key={label}><dt>{countLabels[label]}</dt><dd>{value.toLocaleString()}</dd></div>)}</dl>
        <p>Account API keys, other workspaces, and external Windows/Mac/Azure machines are retained. This action has no undo.</p>
        {preview.data.retained.length ? <p>{preview.data.retained.length} external computer record(s) will remain available in deletion history.</p> : null}
        {preview.data.blockers.map((blocker, index) => <p role="alert" key={`${blocker.code}-${index}`}>{blocker.message} <Link to={blocker.url} onClick={() => setOpen(false)}>Open controls</Link></p>)}
        <form onSubmit={event => { event.preventDefault(); if (!pending && name === preview.data?.workspace_name && !preview.data.blockers.length) void run(() => submit()); }}>
          <label>Type the workspace name to confirm<input value={name} onChange={event => setName(event.target.value)} disabled={busy || !!pending} autoComplete="off" /></label>
          <div className="deletion-actions"><button type="button" disabled={busy || !!pending} onClick={() => void preview.refetch()}>Refresh preview</button>
            <button className="danger" disabled={busy || !!pending || preview.isFetching || name !== preview.data.workspace_name || preview.data.blockers.length > 0}>Delete workspace and contents</button></div>
        </form>
      </> : null}
      {error ? <p role="alert">{error}</p> : null}
    </Dialog>
    <details open={!!notice || !!pending}><summary>Deletion history</summary>
      {history.error ? <p role="alert">{String(history.error)}</p> : null}
      {history.data?.items.length === 0 ? <p>No deleted workspaces.</p> : null}
      {history.data?.items.map(item => <article key={item.request_id}>
        <h3>{item.workspace_name}</h3><p>{new Date(item.deleted_at).toLocaleString()}</p>
        <p>{item.cleanup.state === "complete" ? "Cleanup complete" : item.cleanup.state === "needs_attention" ? "File cleanup needs attention" : "File cleanup pending"} · {item.cleanup.remaining} files remaining</p>
        {item.cleanup.errors.length ? <p role="alert">{item.cleanup.errors.join(", ")}</p> : null}
        {item.cleanup.state !== "complete" ? <button disabled={busy} onClick={() => void run(async () => {
          await post(`/api/workspace-deletions/${item.request_id}/retry-cleanup`, {}); await history.refetch();
        })}>Retry file cleanup</button> : null}
        {item.retained.length ? <RetainedInventory workspaceId={item.workspace_id} /> : null}
      </article>)}
      {cursor > 0 ? <button onClick={() => setCursor(Math.max(0, cursor - 20))}>Newer deletions</button> : null}
      {history.data?.next_cursor != null ? <button onClick={() => setCursor(history.data!.next_cursor!)}>Older deletions</button> : null}
    </details>
  </details>;
}
