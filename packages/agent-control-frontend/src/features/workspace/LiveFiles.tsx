import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api, apiBase } from "../../api/client";
import { useSessionStore } from "../../session/store";

type Entry = {
  path: string;
  name: string;
  kind: string;
  size: number;
  protected: boolean;
};
type Preview = {
  path: string;
  text: string;
  revision?: string;
  returned_bytes: number;
  size?: number;
  truncated: boolean;
  protected: boolean;
};

export function LiveFiles({ botId, sid }: { botId: string; sid: string }) {
  const [path, setPath] = useState("/workspace");
  const [cursor, setCursor] = useState("");
  const [selected, setSelected] = useState<Entry>();
  const changed = useSessionStore(
    (state) => state.sessions[botId]?.filesRevision,
  );
  const base = `/api/bots/${botId}/sessions/${sid}`;
  const files = useQuery({
    queryKey: ["files", botId, sid, path, cursor, changed],
    queryFn: () =>
      api<{ entries: Entry[]; cursor: string | null }>(
        `${base}/files?path=${encodeURIComponent(path)}&cursor=${encodeURIComponent(cursor)}`,
      ),
    refetchInterval: 10000,
  });
  const preview = useQuery({
    queryKey: ["file-preview", sid, selected?.path, changed],
    enabled: !!selected && !selected.protected,
    queryFn: () =>
      api<Preview>(
        `${base}/file-preview?path=${encodeURIComponent(selected!.path)}`,
      ),
  });
  return (
    <section
      aria-label="Workspace files"
      style={{ padding: 16, overflow: "auto", height: "100%" }}
    >
      <div className="row">
        <strong>{path}</strong>
        <button
          onClick={() => {
            setPath(
              path === "/workspace"
                ? path
                : path.slice(0, path.lastIndexOf("/")),
            );
            setCursor("");
          }}
        >
          Up
        </button>
        <button
          onClick={() => {
            void files.refetch();
            void preview.refetch();
          }}
        >
          Refresh files
        </button>
      </div>
      {files.error ? <p role="alert">{files.error.message}</p> : null}
      {files.isPending ? <p>Loading files…</p> : null}
      <ul>
        {files.data?.entries.map((entry) => (
          <li key={entry.path}>
            <button
              onClick={() => {
                if (entry.kind === "directory") {
                  setPath(entry.path);
                  setCursor("");
                  setSelected(undefined);
                } else setSelected(entry);
              }}
            >
              {entry.name}
              {entry.kind === "directory" ? "/" : ""}
            </button>{" "}
            <span>
              {entry.protected
                ? "Protected · metadata only"
                : entry.kind === "unsupported"
                  ? "Unsupported file type"
                  : `${entry.size} bytes`}
            </span>
          </li>
        ))}
      </ul>
      {files.data?.cursor ? (
        <button onClick={() => setCursor(files.data!.cursor!)}>
          Next 200 files
        </button>
      ) : null}
      {cursor ? (
        <button onClick={() => setCursor("")}>First page</button>
      ) : null}
      {selected ? (
        <section aria-label="File preview">
          <h3>{selected.name}</h3>
          {selected.protected ? (
            <p>Protected file. Content is unavailable through file APIs.</p>
          ) : preview.error ? (
            <p role="alert">{preview.error.message}</p>
          ) : preview.data ? (
            <>
              <p>
                {preview.data.truncated
                  ? "Partial preview"
                  : "Complete preview"}{" "}
                · {preview.data.returned_bytes} of {preview.data.size} bytes
              </p>
              <pre style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}>
                {preview.data.text}
              </pre>
              {preview.data.revision ? (
                <a
                  href={`${apiBase()}${base}/file-content?path=${encodeURIComponent(selected.path)}&revision=${preview.data.revision}`}
                  target="_blank"
                  rel="noreferrer"
                >
                  Download complete file
                </a>
              ) : null}
            </>
          ) : (
            <p>Loading preview…</p>
          )}
        </section>
      ) : null}
    </section>
  );
}
