import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "../../api/client";
import { post } from "../workspace/workspaceApi";

type Inventory = { computers: { id: string; resource_id: string; cleanup_state: string }[] };
export function RetainedInventory({ workspaceId }: { workspaceId: string }) {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const inventory = useQuery({ queryKey: ["deleted-workspace-inventory", workspaceId],
    queryFn: () => api<Inventory>(`/api/workspaces/${workspaceId}/compute-inventory`), enabled: open });
  return <details onToggle={event => setOpen(event.currentTarget.open)}>
    <summary>Retained external computers</summary>
    <p>These resources were retained. Reconciliation checks their current state.</p>
    {inventory.error || error ? <p role="alert">{String(inventory.error ?? error)}</p> : null}
    {inventory.data?.computers.map(item => <div key={item.id}>
      <p>{item.resource_id} · {item.cleanup_state}</p>
      <button disabled={busy} onClick={async () => {
        setBusy(true); setError("");
        try { await post(`/api/workspaces/${workspaceId}/compute-inventory/${item.id}/reconcile`, { request_id: crypto.randomUUID() }); await inventory.refetch(); }
        catch (caught) { setError(String(caught)); }
        finally { setBusy(false); }
      }}>Reconcile inventory</button>
    </div>)}
  </details>;
}
