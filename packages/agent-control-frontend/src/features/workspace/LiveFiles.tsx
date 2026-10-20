import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api, apiBase } from "../../api/client";
import { Icon } from "../../components/ui/Icon";
import { EmptyState } from "../../components/ui/EmptyState";
import { useSessionStore } from "../../session/store";
import styles from "./workspace.module.css";

type Entry = {
  path: string;
  name: string;
  kind: string;
  size: number;
  protected: boolean;
};
type Listing = { entries: Entry[]; cursor: string | null };
type Preview = {
  path: string;
  text: string;
  revision?: string;
  returned_bytes: number;
  size?: number;
  truncated: boolean;
  protected: boolean;
};
type TreeProps = {
  botId: string;
  sid: string;
  base: string;
  changed?: number;
  selectedPath?: string;
  onSelect: (entry: Entry) => void;
};

export function LiveFiles({
  botId,
  sid,
  expanded,
}: {
  botId: string;
  sid: string;
  expanded: boolean;
}) {
  const [selected, setSelected] = useState<Entry>();
  const changed = useSessionStore(
    (state) => state.sessions[botId]?.filesRevision,
  );
  const client = useQueryClient();
  const base = `/api/bots/${botId}/sessions/${sid}`;
  const tree: TreeProps = {
    botId,
    sid,
    base,
    changed,
    selectedPath: selected?.path,
    onSelect: setSelected,
  };
  const preview = useQuery({
    queryKey: ["file-preview", sid, selected?.path, changed],
    enabled: !!selected && selected.kind === "file" && !selected.protected,
    queryFn: () =>
      api<Preview>(
        `${base}/file-preview?path=${encodeURIComponent(selected!.path)}`,
      ),
  });
  function refresh() {
    void client.invalidateQueries({ queryKey: ["files", botId, sid] });
    void client.invalidateQueries({ queryKey: ["file-preview", sid] });
  }
  return (
    <div
      className={`${styles.fileWorkbench} ${expanded ? "" : styles.compactFiles}`}
    >
      <nav className={styles.fileTree} aria-label="Workspace files">
        <div className={styles.treeHeader}>
          <p className="eyebrow">Workspace files</p>
          <button type="button" className="ghost" onClick={refresh}>
            Refresh files
          </button>
        </div>
        <DirectoryListing path="/workspace" {...tree} />
      </nav>
      <FilePreview
        base={base}
        selected={selected}
        preview={preview.data}
        error={preview.error}
        loading={preview.isPending}
      />
    </div>
  );
}

function DirectoryListing({ path, ...tree }: TreeProps & { path: string }) {
  const [cursor, setCursor] = useState("");
  const files = useQuery({
    queryKey: ["files", tree.botId, tree.sid, path, cursor, tree.changed],
    queryFn: () =>
      api<Listing>(
        `${tree.base}/files?path=${encodeURIComponent(path)}&cursor=${encodeURIComponent(cursor)}`,
      ),
    refetchInterval: 10000,
  });
  if (files.isPending) return <p>Loading files…</p>;
  if (files.error) return <p role="alert">{files.error.message}</p>;
  const entries = files.data.entries;
  const next = files.data.cursor;
  const directories = entries.filter((entry) => entry.kind === "directory");
  const leaves = entries.filter((entry) => entry.kind !== "directory");
  const rootEmpty = path === "/workspace" && !cursor && entries.length === 0 && !next;
  return (
    <>
      {rootEmpty ? (
        <EmptyState icon="folder" title="No files yet">
          Files created in the sandbox appear in this tree.
        </EmptyState>
      ) : null}
      {!rootEmpty && entries.length === 0 ? (
        <p className={styles.fileLimit}>Empty folder</p>
      ) : null}
      {directories.map((entry) => (
        <Folder key={entry.path} entry={entry} {...tree} />
      ))}
      {leaves.map((entry) => (
        <button
          key={entry.path}
          type="button"
          className={styles.treeFile}
          aria-pressed={entry.path === tree.selectedPath}
          title={entry.path}
          onClick={() => tree.onSelect(entry)}
        >
          <Icon name={entry.protected ? "lock" : "file"} />
          <span>{entry.name}</span>
        </button>
      ))}
      {next ? (
        <button
          type="button"
          className={`${styles.treeMore} ghost`}
          onClick={() => setCursor(next)}
        >
          Next 200 files
        </button>
      ) : null}
      {cursor ? (
        <button
          type="button"
          className={`${styles.treeMore} ghost`}
          onClick={() => setCursor("")}
        >
          First page
        </button>
      ) : null}
    </>
  );
}

function Folder({ entry, ...tree }: TreeProps & { entry: Entry }) {
  const [open, setOpen] = useState(false);
  return (
    <details
      className={styles.treeFolder}
      onToggle={(event) => {
        if (event.target !== event.currentTarget) return;
        setOpen(event.currentTarget.open);
      }}
    >
      <summary>
        <Icon name="folder" />
        <span>{entry.name}</span>
      </summary>
      {open ? (
        <div>
          <DirectoryListing path={entry.path} {...tree} />
        </div>
      ) : null}
    </details>
  );
}

function FilePreview({
  base,
  selected,
  preview,
  error,
  loading,
}: {
  base: string;
  selected?: Entry;
  preview?: Preview;
  error: Error | null;
  loading: boolean;
}) {
  if (!selected)
    return (
      <section className={styles.filePreview} aria-label="File preview">
        <EmptyState icon="file" title="Select a file">
          Choose a file in the workspace tree to preview it.
        </EmptyState>
      </section>
    );
  const protectedFile = selected.protected;
  const unsupported = selected.kind === "unsupported";
  const status = protectedFile
    ? "Protected · metadata only"
    : unsupported
      ? "Unsupported file type"
      : preview
        ? `${preview.truncated ? "Partial preview" : "Complete preview"} · ${preview.returned_bytes} of ${preview.size} bytes`
        : `${selected.size} bytes`;
  return (
    <section className={styles.filePreview} aria-label="File preview">
      <header>
        <Icon name={protectedFile ? "lock" : "file"} />
        <h3 title={selected.path}>{selected.name}</h3>
      </header>
      <div className={styles.previewBody}>
        <div className={styles.previewHeading}>
          <span className="badge">
            {protectedFile
              ? "Protected configuration"
              : unsupported
                ? "Unsupported file"
                : "Workspace file"}
          </span>
          <span>{status}</span>
        </div>
        {protectedFile ? (
          <EmptyState icon="lock" title="Protected file">
            Content is unavailable through file APIs.
          </EmptyState>
        ) : unsupported ? null : error ? (
          <p role="alert">{error.message}</p>
        ) : preview ? (
          <>
            <pre className={styles.fileCode}>{preview.text}</pre>
            {preview.revision ? (
              <a
                href={`${apiBase()}${base}/file-content?path=${encodeURIComponent(selected.path)}&revision=${preview.revision}`}
                target="_blank"
                rel="noreferrer"
              >
                Download complete file
              </a>
            ) : null}
          </>
        ) : loading ? (
          <p>Loading preview…</p>
        ) : null}
      </div>
      <footer>
        <Icon name="folder" />
        <span>{selected.path}</span>
      </footer>
    </section>
  );
}
