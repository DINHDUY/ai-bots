import { useRef, useState } from "react";
import { api, ApiError } from "../../api/client";
import type { ImportCommand, ImportDraft, ImportPreview, ImportResult, SourceFile } from "../../api/imports.generated";

const recoveryKey = "workflow-import-request";
export const emptyDraft = (): ImportDraft => ({
  workspace_name: "", files: [],
  defaults: { framework: "microsoft", credential_id: "", model: "", tool_selection: null },
});

export function useWorkflowImport(onCreated: (result: ImportResult) => Promise<void>) {
  const [deleted, setDeleted] = useState(false);
  const [draft, setDraft] = useState<ImportDraft>(emptyDraft);
  const [preview, setPreview] = useState<ImportPreview | null>(null);
  const [reviewed, setReviewed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [fileErrors, setFileErrors] = useState<Record<string, string>>({});
  const [result, setResult] = useState<ImportResult | null>(null);
  const [pendingId, setPendingId] = useState(() => sessionStorage.getItem(recoveryKey));
  const [hasSubmission, setHasSubmission] = useState(false);
  const submitted = useRef<ImportCommand | null>(null);
  const working = useRef(false);

  function change(next: ImportDraft) {
    if (working.current || submitted.current) return;
    setDraft(next);
    setReviewed(false);
    setError("");
  }

  async function files(selected: File[], replaceId?: string) {
    if (working.current || submitted.current) return;
    if (!selected.length) return;
    if (draft.files.length + (replaceId ? 0 : selected.length) > 50) {
      setError("Select at most 50 files."); return;
    }
    working.current = true;
    setBusy(true);
    const nextErrors = { ...fileErrors };
    const added: SourceFile[] = [];
    for (const file of selected) {
      const id = replaceId ?? crypto.randomUUID();
      let content = "";
      delete nextErrors[id];
      try {
        if (file.size > 65536) throw new Error("File exceeds 64 KiB.");
        if (!file.name.toLowerCase().endsWith(".md")) throw new Error("Select a Markdown (.md) file.");
        content = new TextDecoder("utf-8", { fatal: true, ignoreBOM: true }).decode(await file.arrayBuffer());
      } catch (caught) {
        nextErrors[id] = caught instanceof Error ? caught.message : "Could not read UTF-8 file.";
      }
      added.push({ file_id: id, filename: file.name, content, overrides: {} });
    }
    setDraft(current => ({ ...current, files: replaceId
      ? current.files.map(file => file.file_id === replaceId ? added[0] : file)
      : [...current.files, ...added] }));
    setFileErrors(nextErrors);
    setReviewed(false);
    setBusy(false);
    working.current = false;
  }

  async function review() {
    if (working.current) return;
    setError("");
    if (!draft.files.length || draft.files.length > 50) {
      setError("Select between 1 and 50 files."); return;
    }
    if (draft.files.some(file => fileErrors[file.file_id])) {
      setError("Replace or remove files that could not be read."); return;
    }
    working.current = true;
    setBusy(true);
    try {
      const response = await send<ImportPreview>("/api/workflow-imports/preview", draft);
      setPreview(response);
      setReviewed(true);
    } catch (caught) {
      setError(String(caught));
    } finally {
      setBusy(false); working.current = false;
    }
  }

  async function finish(created: ImportResult) {
    const workspaces = await api<{ id: string }[]>("/api/workspaces");
    const deleted = !workspaces.some(workspace => workspace.id === created.workspace_id);
    setDeleted(deleted);
    setResult(created);
    setPendingId(null);
    sessionStorage.removeItem(recoveryKey);
    submitted.current = null;
    setHasSubmission(false);
    setError("");
    if (deleted) return;
    try {
      await onCreated(created);
    } catch {
      setError("The workspace was imported. Selecting it failed; open it from Workspace settings.");
    }
  }

  async function recover() {
    if (!pendingId || working.current) return;
    working.current = true; setBusy(true);
    try {
      await finish(await api<ImportResult>(`/api/workflow-imports/${pendingId}`));
    } catch (caught) {
      setError(caught instanceof ApiError && caught.status === 404
        ? "No completed receipt yet. Check again, or retry the original import with the same files and settings."
        : "Could not check the import result. Try again when connected.");
    } finally {
      working.current = false; setBusy(false);
    }
  }

  async function commit() {
    if (working.current || result) return;
    if (!submitted.current && (!reviewed || !preview?.valid || !preview.preview_digest)) return;
    const id = pendingId ?? crypto.randomUUID();
    const command = submitted.current ?? { ...draft, request_id: id, preview_digest: preview!.preview_digest! };
    // Store only the recovery ID. Private file contents stay in memory.
    sessionStorage.setItem(recoveryKey, id);
    setPendingId(id);
    submitted.current = command;
    setHasSubmission(true);
    working.current = true; setBusy(true); setError("");
    try {
      await finish(await send<ImportResult>("/api/workflow-imports", command));
    } catch (caught) {
      // A validation rejection has no writes. A network/5xx failure is uncertain.
      if (caught instanceof ApiError && [400, 409, 413, 415, 422].includes(caught.status)) {
        submitted.current = null;
        setHasSubmission(false);
        setReviewed(false);
        // Keep a recovered ID until a receipt lookup establishes its result.
        if (!pendingId) {
          setPendingId(null); sessionStorage.removeItem(recoveryKey);
        }
        setError(`${caught.message} Review the files and preview again.`);
      } else {
        setError("The import result is unknown. Check its result or retry the same import; its request ID is retained.");
      }
    } finally {
      working.current = false; setBusy(false);
    }
  }

  function reset() {
    if (pendingId || working.current) return;
    setDraft(emptyDraft()); setPreview(null); setReviewed(false);
    setResult(null); setDeleted(false); setError(""); setFileErrors({});
  }

  return { deleted, draft, preview, reviewed, busy, error, fileErrors, result, pendingId,
    locked: busy || hasSubmission, change, files, review, commit, recover, reset };
}

async function send<T>(path: string, value: unknown): Promise<T> {
  const body = JSON.stringify(value);
  if (new TextEncoder().encode(body).length > 1048576) throw new ApiError(413, "Encoded import exceeds 1 MiB.");
  return api<T>(path, { method: "POST", body });
}
