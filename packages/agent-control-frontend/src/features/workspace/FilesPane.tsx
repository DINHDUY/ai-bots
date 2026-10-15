import { useMemo } from "react";
import type { FileEntry } from "../../session/reduce";
import {
  clockLabel,
  observedFiles,
  protectedFile,
} from "../../session/selectors";
import { useWorkspaceUi } from "../../session/workspaceUiStore";
import { Icon } from "../../components/ui/Icon";
import { CopyButton } from "../../components/ui/CopyButton";
import { EmptyState } from "../../components/ui/EmptyState";
import styles from "./workspace.module.css";
import { useSessionStore } from "../../session/store";
import { LiveFiles } from "./LiveFiles";

type Folder = { folders: Map<string, Folder>; files: FileEntry[] };
function makeTree(files: FileEntry[]): Folder {
  const root: Folder = { folders: new Map(), files: [] };
  for (const file of files) {
    const parts = file.path.replaceAll("\\", "/").split("/").filter(Boolean);
    parts.pop();
    let folder = root;
    for (const part of parts) {
      if (!folder.folders.has(part))
        folder.folders.set(part, { folders: new Map(), files: [] });
      folder = folder.folders.get(part)!;
    }
    folder.files.push(file);
  }
  return root;
}
export function FilesPane(props: { botId: string; files: FileEntry[]; expanded: boolean }) {
  const session = useSessionStore(state => state.sessions[props.botId]);
  return session?.health?.services.files && session.sessionId ? <LiveFiles botId={props.botId} sid={session.sessionId} /> : <LegacyFilesPane {...props} />;
}
function LegacyFilesPane({
  botId,
  files,
  expanded,
}: {
  botId: string;
  files: FileEntry[];
  expanded: boolean;
}) {
  const selected = useWorkspaceUi((state) => state.bots[botId]?.filePath);
  const patch = useWorkspaceUi((state) => state.patch);
  const latest = useMemo(() => observedFiles(files), [files]);
  const tree = useMemo(() => makeTree(latest), [latest]);
  const file = latest.find((item) => item.path === selected) ?? latest[0];
  if (!file)
    return (
      <EmptyState icon="folder" title="No files observed yet">
        Files reported by the agent appear here. This view is not a full listing
        of the sandbox.
      </EmptyState>
    );
  const protectedPreview = protectedFile(file.path);
  const name = file.path.replaceAll("\\", "/").split("/").at(-1);
  function folderView(folder: Folder): React.ReactNode {
    return (
      <>
        {[...folder.folders.entries()]
          .sort(([a], [b]) => a.localeCompare(b))
          .map(([name, child]) => (
            <details key={name} open className={styles.treeFolder}>
              <summary>
                <Icon name="folder" />
                <span>{name}</span>
              </summary>
              <div>{folderView(child)}</div>
            </details>
          ))}
        {folder.files.map((item) => (
          <button
            key={item.path}
            className={styles.treeFile}
            aria-pressed={item.path === file?.path}
            title={item.path}
            onClick={() => patch(botId, { filePath: item.path })}
          >
            <Icon name={protectedFile(item.path) ? "lock" : "file"} />
            <span>{item.path.replaceAll("\\", "/").split("/").at(-1)}</span>
          </button>
        ))}
      </>
    );
  }
  return (
    <div
      className={`${styles.fileWorkbench} ${expanded ? "" : styles.compactFiles}`}
    >
      <nav className={styles.fileTree} aria-label="Observed files">
        <p className="eyebrow">
          Observed files <span> / {latest.length}</span>
        </p>
        {folderView(tree)}
        <p className={styles.fileLimit}>Reported during this page session.</p>
      </nav>
      <section className={styles.filePreview}>
        <header>
          <Icon name={protectedPreview ? "lock" : "file"} />
          <h3 title={file.path}>{name}</h3>
        </header>
        <div className={styles.previewBody}>
          <div className={styles.previewHeading}>
            <span className="badge">
              {protectedPreview
                ? "Protected configuration"
                : "Reported preview"}
            </span>
            {file.at ? <span>Received {clockLabel(file.at)}</span> : null}
          </div>
          {protectedPreview ? (
            <EmptyState icon="lock" title="Configuration preview hidden">
              Credential files are concealed in this view.
            </EmptyState>
          ) : (
            <>
              <pre className={styles.fileCode}>
                {file.preview || "No preview content was reported."}
              </pre>
              <CopyButton label="Copy preview" text={file.preview} />
              <p className={styles.fileLimit}>
                This preview may be truncated. Complete file contents and
                downloads are not available.
              </p>
            </>
          )}
        </div>
        <footer>
          <Icon name="folder" />
          <span>{file.path}</span>
        </footer>
      </section>
    </div>
  );
}
